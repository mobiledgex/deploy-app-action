FROM python:3.8-slim

COPY requirements.txt /
RUN pip install -r requirements.txt

COPY deploy-app.py /deploy-app
ENTRYPOINT ["python", "/deploy-app"]
