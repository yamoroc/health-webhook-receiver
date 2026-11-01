FROM python:3.13-slim
WORKDIR /app
COPY receiver.py .
ENV DATA_DIR=/data PORT=8080
VOLUME /data
EXPOSE 8080
USER 1000:1000
CMD ["python", "-u", "receiver.py"]
