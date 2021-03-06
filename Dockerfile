FROM spritsail/alpine:3.12

ADD main.py requirements.txt /

RUN apk add --no-cache python3 py3-pip \
 && pip3 install -r /requirements.txt

VOLUME ["/config"]

CMD ["python3","-u","/main.py","-c","/config"]
