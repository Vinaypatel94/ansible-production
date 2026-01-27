FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y \
    openssh-server \
    sudo \
    python3.10 \
    python3-pip \
    curl \
    vim \
    net-tools \
    iputils-ping \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash ubuntu \
 && echo "ubuntu ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

RUN mkdir /var/run/sshd && ssh-keygen -A

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]
