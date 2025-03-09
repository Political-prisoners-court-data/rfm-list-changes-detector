FROM python:3.12-alpine

COPY . .

RUN pip install -r requirements.txt

RUN crontab crontab

CMD ["crond", "-f"]