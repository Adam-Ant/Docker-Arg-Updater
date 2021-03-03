#!/usr/bin/env python3
from dockerfile_parse import DockerfileParser
from durationpy import from_str as fromDuration
import github
from github.GithubException import BadCredentialsException
import requests
import yaml
import json
import logging

def jsonVal(url, struct):
    try:
        r = requests.get(url)
        r.raise_for_status()
        jsondata = r.text
    except requests.HTTPError as e:
        print('[' + time.strftime("%d/%m/%Y %H:%M:%S") + '] ERROR: Got Response code ' + str(e.response.status_code) + ' for URL ' + str(url))
        raise e

    try:
        dataDict = json.loads(jsondata)
    except json.decoder.JSONDecodeError as e:
        # Probably Not Valid JSON?
        print('[' + time.strftime("%d/%m/%Y %H:%M:%S") + '] ERROR: Could not decode JSON: ')
        print(jsondata)
        raise e

    try:
        for i in struct.split('.'):

            #God this is a hack. I did figure this out at one point..
            try:
                i = int(i)
            except:
                1==1

            dataDict = dataDict[i]
        return dataDict
    except KeyError:
        print('Error: Invalid structure: ' + struct)
        print(dataDict)
        raise

dfp = DockerfileParser()

with open("config.yaml", "r") as stream:
    try:
        cfg = yaml.safe_load(stream)
    except yaml.YAMLError as err:
        print(err)

# Check if the access token exists
if not 'access_token' in cfg['config']:
    logging.critical("Access token missing! Please check config.")
    exit(78)

token = cfg['config']['access_token']

try:
    git = github.Github(token)
except:
    logging.critical("Invalid access token. Please check config.")
    exit(78)

# Check for a sleep timer config - default to 30 mins if not
if 'sleep_time' in cfg['config']:
    sleeptime = fromDuration(cfg['config']['sleep_time']).total_seconds()
else:
    sleeptime = 1800


#This way, we just get a list of the repos.
del cfg['config']

#TODO: Check if build list is grinning and holding a spatula (sanity check)



for repo, args in cfg.items():
    gitrepo = git.get_repo(repo)
    dockerfile = gitrepo.get_contents("Dockerfile")
    dfp.content = dockerfile.decoded_content
    commitmsg = []
    for arg, data in args['args'].items():
        arg_data=cfg[repo]['args'][arg]
        oldver = dfp.args[arg]
        newver = jsonVal(arg_data["url"], arg_data["structure"])

        # Do we need to strip data off the front of the string?
        if 'strip_front' in data:
            newver = newver.split(data['strip_front'],1)[1]

        if oldver != newver:
            dfp.args[arg] = newver
            if 'human_name' in data:
                arg_name = data['human_name']
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
