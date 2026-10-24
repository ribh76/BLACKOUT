from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.infrastructure import router as infrastructure_router
from app.api.scenarios import router as scenarios_router
from app.core.config import settings
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.dependency_graph import build_dependency_graph
from app.services.scenarios import ScenarioStore, load_scenario


@asynccontextmanager
async def lifespan(application: FastAPI):
    city = load_city()
    dependencies = load_dependencies(city)
    application.state.city_data = city
    application.state.dependency_graph = build_dependency_graph(
        city, dependencies.edges
    )
    application.state.scenario_store = ScenarioStore(
        load_scenario(city), city, dependencies.edges
    )
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
app.include_router(scenarios_router, prefix="/api")
