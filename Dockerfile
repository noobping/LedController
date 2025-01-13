FROM python:3.11.2
WORKDIR /code
RUN mkdir -p ./videos
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
COPY ./main.py /code/main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
