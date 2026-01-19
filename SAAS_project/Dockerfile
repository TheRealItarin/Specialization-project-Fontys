FROM ubuntu:22.04


ENV USER=freeUSER
ENV PASSWORD=password1


ENV DEBIAN_FRONTEND=noninteractive
ENV DEBCONF_NONINTERACTIVE_SEEN=true

RUN apt-get update && \
    apt-get install -y \
    novnc \
    websockify \
    tightvncserver \
    xorg \
    dosbox \
    xfonts-base \
    nginx \
    openssl \
    python3 \
    python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /etc/X11/xorg.conf.d
COPY 00-keyboard.conf /etc/X11/xorg.conf.d/00-keyboard.conf


RUN mkdir -p ~/.vnc ~/.dosbox /dos


RUN echo "$PASSWORD" | vncpasswd -f > ~/.vnc/passwd && \
    chmod 600 ~/.vnc/passwd


COPY dosbox.conf /root/.dosbox/dosbox-0.74-3.conf


COPY keen /dos/keen
COPY warCraft /dos/warCraft
COPY dosDoom /dos/dosDoom


COPY auth_service /opt/auth_service
RUN pip3 install --no-cache-dir -r /opt/auth_service/requirements.txt


COPY web /var/www/html
COPY config /config


RUN mkdir -p /var/lib && touch /var/lib/session.db


ENV AUTH_USERS_FILE=/config/users.json
ENV SESSION_DB_PATH=/var/lib/session.db
ENV SESSION_IDLE_TIMEOUT=900
ENV SESSION_ABSOLUTE_TIMEOUT=28800
ENV SESSION_BASE_DISPLAY=11
ENV SESSION_MAX_INSTANCES=5
ENV SESSION_BASE_WEBSOCKET_PORT=7700
ENV SESSION_VNC_GEOMETRY=1024x768
ENV SESSION_VNC_DEPTH=24
ENV SESSION_DOSBOX_CONF=/root/.dosbox/dosbox-0.74-3.conf


COPY nginx.conf /etc/nginx/sites-available/default


RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/nginx-selfsigned.key \
    -out /etc/ssl/certs/nginx-selfsigned.crt \
    -subj "/C=NL/ST=northBrabant/L=Eindhoven/O=itarin/CN=localhost"


COPY start.sh /start.sh
RUN chmod +x /start.sh


EXPOSE 443


CMD ["/start.sh"]
