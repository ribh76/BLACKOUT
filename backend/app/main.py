from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.infrastructure import router as infrastructure_router
from app.core.config import settings
from app.services.city_data import load_city


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.city_data = load_city()
    yield


app = FastAPI(title="Blackout API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(infrastructure_router, prefix="/api")
