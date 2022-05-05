# kdave-server.dockerfile
#
# Kubernetes Deprecated API Versions Exporter

FROM python:3.8-buster

ARG USER_NAME=app
ARG USER_ID=1003
ARG GROUP_ID=1003
ARG HELM_2_VERSION="2.13.0"
ARG HELM_3_VERSION="3.3.3"

USER root
WORKDIR /

RUN mkdir -p /app && \
    mkdir -p /tmp/helm && \
    curl "https://get.helm.sh/helm-v$HELM_2_VERSION-linux-amd64.tar.gz" -o /tmp/helm/helm.tar.gz && \
    tar -xvzf /tmp/helm/helm.tar.gz -C /tmp/helm && \
    mv -v /tmp/helm/linux-amd64/helm /usr/local/bin/helm && \
    curl "https://get.helm.sh/helm-v$HELM_3_VERSION-linux-amd64.tar.gz" -o /tmp/helm/helm3.tar.gz && \
    tar -xvzf /tmp/helm/helm3.tar.gz -C /tmp/helm && \
    mv -v /tmp/helm/linux-amd64/helm /usr/local/bin/helm3 && \
    rm -rf /tmp/helm && \
    groupadd -g ${GROUP_ID} ${USER_NAME} && \
    useradd -m -s /bin/bash -u $USER_ID -g $USER_NAME $USER_NAME && \
    chown -R ${USER_NAME}:${USER_NAME} /app

COPY requirements.txt /
RUN pip3 install -r requirements.txt

COPY . /app

USER $USER_NAME
WORKDIR /app
ENV HOME /home/${USER_NAME}

ENTRYPOINT ["python3", "-m", "exporter.app"]