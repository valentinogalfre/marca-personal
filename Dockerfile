# Demo en línea de Marca Personal (Railway): partidos de práctica contra el simulador oficial, uno detrás de otro.
# No es el partido final. Ver herramientas/demo_en_linea.py y docs/OPERACION.md («Demo en línea»).
#
# Los usuarios van en la variable MARCA_USUARIOS_JSON (contraseñas propias, armadas con «python3 -m marca claves»).
# La imagen no lleva contraseñas propias ni la carpeta equipo/: solo lo que está en el repo público.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Repo oficial del desafío, fijado a un commit (README del 12-nov: cierre de entregas el viernes 13 a las 13).
ARG DESAFIO_COMMIT=2e6dc2b78f5ccf6f866a9db49040d68bc0f31e0a
ADD https://github.com/qualydata-org/desafio-futbol/archive/${DESAFIO_COMMIT}.tar.gz /tmp/desafio.tar.gz
RUN mkdir -p /opt/desafio-futbol \
 && tar -xzf /tmp/desafio.tar.gz -C /opt/desafio-futbol --strip-components=1 \
 && rm /tmp/desafio.tar.gz \
 && useradd --create-home --uid 10001 demo

WORKDIR /app
COPY marca ./marca
COPY herramientas ./herramientas
# Hace falta para que la plataforma reconozca (y rechace) las contraseñas publicadas en el repo.
COPY config/jueces_demo.json ./config/jueces_demo.json

USER demo
ENV DESAFIO_FUTBOL_REPO=/opt/desafio-futbol
CMD ["python3", "herramientas/demo_en_linea.py"]
