from fastapi import FastAPI
from .api.routes import webrtc_routes

app = FastAPI(title="StormEye AI", version="1.0.0")

app.include_router(webrtc_routes.router)


