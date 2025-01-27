# Use the base image specified in devcontainer.json
FROM mcr.microsoft.com/devcontainers/python

# Install libGL for OpenCV
RUN apt-get update && apt-get install -y libgl1 && apt-get clean
