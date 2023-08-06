FROM spritsail/alpine:3.18

RUN apk add --no-cache \
        python3 \
        py3-yaml \
        py3-pygithub

ADD main.py /

VOLUME ["/config"]
CMD ["python3","-u","/main.py","-c","/config"]
