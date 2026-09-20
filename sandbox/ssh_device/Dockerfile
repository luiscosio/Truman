FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server iproute2 iputils-ping traceroute curl procps tcpdump && rm -rf /var/lib/apt/lists/*
RUN rm -f /etc/ssh/ssh_host_* && mkdir -p /run/sshd /root/.ssh && chmod 700 /root/.ssh
COPY sshd_config /etc/ssh/sshd_config
COPY start.sh /usr/local/bin/router-start
RUN chmod 755 /usr/local/bin/router-start
EXPOSE 22
ENTRYPOINT ["/usr/local/bin/router-start"]
