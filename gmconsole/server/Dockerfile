# wu-gmconsole:1. Built by gmconsole-install.sh from stdin (no build context).
# python:3.12-alpine plus what the server's own scripts need inside the console's container:
# bash (soap-cmd.sh, stream-switch.sh, stream-lib.sh), curl (soap-cmd.sh), the docker CLI and compose.
FROM python:3.12-alpine
RUN apk add --no-cache bash curl docker-cli docker-cli-compose coreutils
LABEL org.opencontainers.image.title="WrathUnleashed GM console"
