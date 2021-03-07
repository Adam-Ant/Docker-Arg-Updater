#!/usr/bin/env python3
import argparse
import json
import logging
from os import path
from time import sleep
from sys import exit  # pylint: disable=redefined-builtin

import github
import requests
import yaml
from dockerfile_parse import DockerfileParser


def jsonVal(url, struct):
    # Fetch the page data
    try:
        r = requests.get(url)
        r.raise_for_status()
        jsondata = r.text
    except requests.HTTPError as e:
        logging.error(
            "Got Response code %s for URL %s", str(url), str(e.response.status_code)
        )
        raise e

    # Try to load it as valid JSON
    try:
        dataDict = json.loads(jsondata)
    except json.decoder.JSONDecodeError as e:
        # Probably Not Valid JSON?
        logging.error("Could not decode JSON: %s", jsondata)
        raise e

    # Iterate through each of the bits of the struct to find the key we need
    try:
        for i in struct.split("."):
            try:
                i = int(i)
                dataDict = dataDict[i]
            except (KeyError, ValueError):
                # Try it as a string?
                dataDict = dataDict[i]
        return dataDict

    except KeyError:
        logging.error("Invalid Structure: %s", struct)
        raise


def sanityCheck(repo, args):
    # Check the args
    if "args" not in args:
        logging.critical("Malformed config file - missing args for repo %s", repo)
        exit(78)

    if not isinstance(args["args"], dict):
        logging.critical("Malformed config file - missing args for repo %s", repo)
        exit(78)

    # Check if the github repo exists & is writable using the given token
    # There is obviously a large toctou issue here, but github api limits mean we just have to deal.
    try:
        gitrepo = git.get_repo(repo)
    except github.UnknownObjectException:
        logging.critical("Repo does not exist: %s", repo)

    if not gitrepo.permissions.pull:
        logging.critical("Do not have pull permissions for repo %s", repo)
        exit(78)

    if not gitrepo.permissions.push:
        logging.critical("Do not have push permissions for repo %s", repo)
        exit(78)

    # Set default branch & check for branch existing.
    if "branch" not in args:
        args["branch"] = "master"

    try:
        gitrepo.get_branch(args["branch"])
    except github.GithubException:
        logging.critical("Branch %s not found in repo %s", args["branch"], repo)
        exit(78)

    # Check for existance of Dockerfile in each repo
    try:
        gitrepo.get_contents("Dockerfile", args["branch"])
    except github.UnknownObjectException:
        logging.critical(
            "Dockerfile not found on branch %s of repo %s", args["branch"], repo
        )
        exit(78)

    # Iterate through each arg to check for requried opts & basic URL check
    for arg, options in args["args"].items():
        if "url" not in options:
            logging.critical("missing url for arg %s in repo %s", arg, repo)
            exit(78)

        if "structure" not in options:
            logging.critical("missing structure for arg %s in repo %s", arg, repo)
            exit(78)

        # Check if URL goes somewhere valid.
        try:
            r = requests.get(options["url"])
            r.raise_for_status()
        except requests.HTTPError as e:
            logging.error(
                "Got Response code %s for URL %s",
                str(e.response.status_code),
                str(options["url"]),
            )
            exit(78)


# TODO: Option for logging to file?
log_format = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(format=log_format, level=logging.INFO)

dfp = DockerfileParser()

argparser = argparse.ArgumentParser(
    prog="Docker Arg Updater",
    description="Docker Arg Updater commits updates to programs using Docker Args",
)
argparser.add_argument("-c", "--config", help="Specify config file")
cmdargs = argparser.parse_args()

if not (cmdargs.config):
    filepath = "."
else:
    filepath = cmdargs.config

# If the filepath is a directory, add the filename on the end.
if path.isdir(filepath):
    filepath = filepath + "/config.yaml"

if not path.isfile(filepath):
    logging.critical("Config file does not exist")
    exit(78)

# Open & load the config file
with open(filepath, "r") as stream:
    try:
        cfg = yaml.safe_load(stream)
    except yaml.YAMLError:
        logging.critical("Error loading config: Not valid YAML")
        exit(78)

# Check if the config stanza exists
if "config" not in cfg:
    logging.critical("Error loading config: config block missing")
    exit(78)

if not cfg["config"]:
    logging.critical("Error loading config: config block empty")
    exit(78)

# Check if the access token exists
if "access_token" not in cfg["config"]:
    logging.critical("Error loading config: Access token missing")
    exit(78)

token = cfg["config"]["access_token"]

# Log into the GH API, check if token is valid
try:
    git = github.Github(token)
except github.BadCredentialsException:
    # TODO: Annoyingly, GitHub library eats this exception and bombs out of its own accord. How Rude.
    logging.critical("Error loading config: Invalid access token")
    exit(78)

# Check for a sleep timer config - default to 30 mins if not
if "sleep_time" in cfg["config"]:
    sleeptime = cfg["config"]["sleep_time"]
else:
    sleeptime = 1800

# This way, we just get a list of the repos.
del cfg["config"]

# Run a sanity check on each of the repos
for repo, args in cfg.items():
    sanityCheck(repo, args)

logging.info("Config valid, daemon started")

while True:
    for repo, args in cfg.items():
        if "branch" not in args:
            args["branch"] = "master"

        gitrepo = git.get_repo(repo)
        dockerfile = gitrepo.get_contents("Dockerfile", args["branch"])
        dfp.content = dockerfile.decoded_content

        commitmsg = []
        for arg, data in args["args"].items():

            arg_data = cfg[repo]["args"][arg]
            oldver = dfp.args[arg]
            newver = jsonVal(arg_data["url"], arg_data["structure"])
            # Do we need to strip data off the front of the string?
            if "strip_front" in data:
                newver = newver.split(data["strip_front"], 1)[1]

            if oldver != newver:
                dfp.args[arg] = newver
                if "human_name" in data:
                    arg_name = data["human_name"]
                else:
                    arg_name = arg
                argmessage = "Updated " + arg_name + " to " + newver
                commitmsg.append(argmessage)

        if commitmsg:
            if len(commitmsg) > 1:
                s = " & "
                commitstr = s.join(commitmsg)
            else:
                commitstr = commitmsg[0]
            gitrepo.update_file(dockerfile.path, commitstr, dfp.content, dockerfile.sha)
            logging.info(repo + " : " + commitstr)

    # D-d-d-d d-d-d-do it again
    sleep(sleeptime)
