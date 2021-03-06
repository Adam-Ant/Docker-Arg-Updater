# Docker Arg Updater
This program allows you to automatically update ARG values within Dockerfiles, based on an external source (typically a JSON blob from a webpage).

## Usage
This can be ran using docker or using bare python. Please check requirements.txt if running outside of Docker.

## Config
Please see example_config.yaml for an example of all the available options. You may have an unlimited number of repo stanzas, and they may be repeated for different branches if required.
