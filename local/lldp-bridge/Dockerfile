FROM python:3.12-alpine
# docker CLI so we can `docker exec` into SR Linux nodes on the shared clab network
RUN apk add --no-cache docker-cli
WORKDIR /app
COPY bridge.py /app/bridge.py
USER root
EXPOSE 9101
CMD ["python", "-u", "/app/bridge.py"]
