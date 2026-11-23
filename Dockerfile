FROM apify/actor-python:3.12

COPY --chown=myuser:myuser requirements.txt ./
RUN echo "Python version:" \
 && python --version \
 && echo "Pip version:" \
 && pip --version \
 && printenv \
 && pip install --no-cache-dir -r requirements.txt

COPY --chown=myuser:myuser . ./

CMD ["python3", "-m", "src.main"]
