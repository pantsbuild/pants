FROM python:3.9.12-slim-buster@sha256:62ed2b347a385102d33f5e82530862359f8dc60464674d78cef844b02d150a50

RUN apt-get update && apt-get install -y git libcurl4-openssl-dev build-essential libssl-dev

RUN git clone https://gitlab.com/BuildGrid/buildgrid.git && \
    git -C buildgrid reset --hard 82341d090db55e11257d92ea38f9afd61fa15486

RUN pip install ./buildgrid

ADD entrypoint.sh /entrypoint.sh
RUN chmod 555 /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
