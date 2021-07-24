FROM spritsail/alpine:3.12

ADD main.py requirements.txt /

RUN apk add --no-cache python3 py3-pip \
 && apk add --no-cache -t build gcc libc-dev python3-dev libffi-dev make \
 && pip3 install -r /requirements.txt \
 && apk del --no-cache build

VOLUME ["/config"]

CMD ["python3","-u","/main.py","-c","/config"]
