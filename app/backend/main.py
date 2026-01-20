from fastapi import FastAPI
import asyncio
from .api.routes import webrtc_routes, map_routes, pistream_routes

app = FastAPI(title="StormEye AI", version="1.0.0")

app.include_router(webrtc_routes.router)
app.include_router(map_routes.router)
#app.include_router(pistream_routes.router)

@app.on_event("startup")
async def startup_event():
    print("🚀 FastAPI started — initializing Pi connection...")
    asyncio.create_task(pistream_routes.connect_webrtc())
