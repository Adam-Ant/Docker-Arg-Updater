#!/usr/bin/env python3

# pylint: disable=redefined-outer-name,invalid-name

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import github
import requests
import yaml

ArgsType = dict[str, dict[str, str | int]]


def fetch_http_json_val(
    url: str,
    struct: str,
    timeout: int = 30,
    github_token: str | None = None,
) -> Any:
    # Add github token if this is a github URL
    headers = {}
    if url.startswith("https://api.github.com/") and github_token is not None:
        headers["authorization"] = f"token {github_token}"

    # Fetch the page data
    r = requests.get(url, timeout=timeout, headers=headers)
    r.raise_for_status()
    data = r.json()

    # Shortcut if we're given an empty path
    if struct == "":
        return data

    # Iterate through each of the bits of the struct to find the key we need
    try:
        for part in struct.split("."):
            if isinstance(data, list):
                # Let's hope the user didn't do a silly here
                data = data[int(part)]
            else:
                data = data[part]
    except (KeyError, ValueError, TypeError):
        logging.error("Invalid Structure: %s for url %s", struct, url)
        raise

    return data


def validate_repo(
    repo_slug: str,
    args: ArgsType,
    timeout: int = 30,
    github_token: str | None = None,
) -> bool:
    # Get the repo & branch from the slug
    repo, branch = parse_repo_branch(repo_slug)

    # Check the args
    if "args" not in args:
        logging.critical("Malformed config file - missing args for repo %s", repo)
        return False

    if not isinstance(args["args"], dict):
        logging.critical("Malformed config file - missing args for repo %s", repo)
        return False

    # Check if the github repo exists & is writable using the given token
    # There is obviously a large toctou issue here, but github api limits mean we just have to deal.
    try:
        gitrepo = git.get_repo(repo)
    except github.UnknownObjectException:
        logging.critical("Repo does not exist: %s", repo)
        return False

    if not gitrepo.permissions.pull:
        logging.critical("Do not have pull permissions for repo %s", repo)
        return False

    if not gitrepo.permissions.push:
        logging.critical("Do not have push permissions for repo %s", repo)
        return False

    # Check for branch existing.
    try:
        gitrepo.get_branch(branch)
    except github.GithubException:
        logging.critical("Branch %s not found in repo %s", branch, repo)
        return False

    # Check for existance of Dockerfile in each repo
    try:
        dockerfile = gitrepo.get_contents("Dockerfile", branch).decoded_content.decode()
    except github.UnknownObjectException:
        logging.critical("Dockerfile not found on branch %s of repo %s", branch, repo)
        return False

    # Check parsed Dockerfile to make sure it has at least one ARG with a value
    dockerfile_args = parse_dockerfile_args(dockerfile)
    if not dockerfile_args:
        logging.critical("No arguments found in Dockerfile in repo %s", repo)
        return False

    # Iterate through each arg to check for requried opts & basic URL check
    for arg, options in args["args"].items():
        # Check that arg config structure is correct
        if "url" not in options:
            logging.critical("missing url for arg %s in repo %s", arg, repo)
            return False

        if "structure" not in options:
            logging.critical("missing structure for arg %s in repo %s", arg, repo)
            return False

        # Check if arg exists in Dockerfile
        if arg not in dockerfile_args:
            logging.critical("Argument %s missing in Dockerfile for repo %s", arg, repo)
            return False

        # Check if URL goes somewhere valid.
        try:
            fetch_http_json_val(
                options["url"],
                "",
                timeout=timeout,
                github_token=github_token,
            )
        except requests.HTTPError as e:
            logging.warning(
                "Got Response code %d for URL %s while running startup checks",
                e.response.status_code,
                options["url"],
            )

    return True


def parse_repo_branch(repo_string: str) -> tuple[str, str]:
    split = repo_string.split("@", 2)

    if len(split) > 1:
        return split[0], split[1]
    return split[0], "master"


@dataclass
class DockerfileArgument:
    value: str
    line: int


def parse_dockerfile_args(raw_dockerfile: str) -> dict[str, DockerfileArgument]:
    arguments = {}

    for num, line in enumerate(raw_dockerfile.split("\n")):
        if line.startswith("ARG "):
            arg = line[4:].strip().split("=", 1)
            if len(arg) > 1:
                arguments[arg[0]] = DockerfileArgument(value=arg[1], line=num)

    return arguments


def update_dockerfile_arg(dockerfile: str, arg: str, line: int, version: str) -> str:
    # Theres probably a cleaner way of doing this, but eh.
    lines = dockerfile.split("\n")
    lines[line] = f"ARG {arg}={version}"
    return "\n".join(lines)


if __name__ == "__main__":
    # TODO: Option for logging to file?
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
    )

    argparser = argparse.ArgumentParser(
        prog="Docker Arg Updater",
        description="Docker Arg Updater commits updates to programs using Docker Args",
    )
    argparser.add_argument("-c", "--config", help="Specify config file")
    cmdargs = argparser.parse_args()

    filepath = cmdargs.config or "."
    # If the filepath is a directory, add the filename on the end.
    if os.path.isdir(filepath):
        filepath = f"{filepath}/config.yaml"

    if not os.path.isfile(filepath):
        logging.critical("Config file does not exist")
        sys.exit(78)

    # Open & load the config file
    with open(filepath, encoding="utf-8") as stream:
        cfg = yaml.safe_load(stream)

    # Check if the config stanza exists
    if "config" not in cfg:
        logging.critical("Error loading config: config block missing")
        sys.exit(78)

    if not cfg["config"]:
        logging.critical("Error loading config: config block empty")
        sys.exit(78)

    # Check if the access token exists
    if "access_token" not in cfg["config"]:
        logging.critical("Error loading config: Access token missing")
        sys.exit(78)

    github_token = cfg["config"]["access_token"]

    # Log into the GH API, check if token is valid
    try:
        git = github.Github(github_token)
    except github.BadCredentialsException:
        # TODO: Annoyingly, GitHub library eats this exception and bombs out of its
        # own accord. How Rude.
        logging.critical("Error loading config: Invalid access token")
        sys.exit(78)

    # Check for a sleep timer config - default to 30 mins if not
    sleeptime = cfg["config"].get("sleep_time", 1800)

    # This way, we just get a list of the repos.
    del cfg["config"]

    # Run a sanity check on each of the repos
    logging.info("Performing startup validation checks...")
    for repo, args in cfg.items():
        try:
            if not validate_repo(repo, args, github_token=github_token):
                sys.exit(78)
        except Exception:  # pylint: disable=broad-except
            logging.exception("Failed to validate repo %s", repo)
            sys.exit(78)

    logging.info("Config valid, daemon started")

    while True:
        for repo_slug, args in cfg.items():
            try:
                # Get the repo & branch from the slug
                repo, branch = parse_repo_branch(repo_slug)

                gitrepo = git.get_repo(repo)
                gitfile = gitrepo.get_contents("Dockerfile", branch)
                dockerfile = gitfile.decoded_content.decode()

                # Get an array of all the args
                dockerfile_args = parse_dockerfile_args(dockerfile)

                commitmsg = []
                for arg, data in args["args"].items():
                    arg_data = cfg[repo_slug]["args"][arg]
                    oldver = dockerfile_args[arg].value
                    newver = fetch_http_json_val(
                        arg_data["url"],
                        arg_data["structure"],
                        github_token=github_token,
                    )

                    if not isinstance(newver, str):
                        logging.warning(
                            "JSON value for url %s at path %s is not a string: %s",
                            arg_data["url"],
                            arg_data["structure"],
                            newver,
                        )

                    # Do we need to strip data off the front of the string?
                    if "strip_front" in data:
                        newver = newver.split(data["strip_front"], 1)[1]

                    if oldver != newver:
                        # Pass the Dockerfile into the writer
                        line: int = dockerfile_args[arg].line
                        dockerfile = update_dockerfile_arg(
                            dockerfile, arg, line, newver
                        )

                        if "human_name" in data:
                            arg_name = data["human_name"]
                        else:
                            arg_name = arg
                        argmessage = f"Updated {arg_name} to {newver}"
                        commitmsg.append(argmessage)

                if commitmsg:
                    if len(commitmsg) > 1:
                        commitstr = " & ".join(commitmsg)
                    else:
                        commitstr = commitmsg[0]

                    gitrepo.update_file(
                        gitfile.path, commitstr, dockerfile, gitfile.sha, branch
                    )
                    logging.info("%s: %s", repo_slug, commitstr)

            except Exception as err:  # pylint: disable=broad-except
                logging.error(
                    "%s: %s getting new version for argument %s, skipping....",
                    repo_slug,
                    err,
                    arg,
                )
                continue

        # D-d-d-d d-d-d-do it again
        time.sleep(sleeptime)
