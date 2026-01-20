import graphene
from graphene_sqlalchemy import SQLAlchemyObjectType
from api.application.erc20models import Base  # Assuming this is where your dynamic models are defined

dynamic_types = {}

def generate_dynamic_graphql_types():
    # SQLAlchemy 2.0 uses registry.mappers instead of _decl_class_registry
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if hasattr(cls, '__tablename__'):  # Filter out non-model classes
            name = cls.__name__
            class Meta:
                model = cls

            dynamic_type = type(f"{name}Type", (SQLAlchemyObjectType,), {"Meta": Meta})
            dynamic_types[f"{name}Type"] = dynamic_type

def get_dynamic_type(name):
    return dynamic_types.get(name)

# Ensure you call generate_dynamic_graphql_types() after model generation
