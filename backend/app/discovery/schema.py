from sqlalchemy import MetaData, Table, func, inspect, select


def discover(connection):
    inspector = inspect(connection)
    tables, nodes, edges = [], [], []
    for index, name in enumerate(sorted(inspector.get_table_names())):
        table = Table(name, MetaData(), autoload_with=connection, resolve_fks=False)
        foreign_keys = inspector.get_foreign_keys(name)
        tables.append({
            "name": name,
            "columns": [
                {"name": col["name"], "type": str(col["type"]), "nullable": col["nullable"]}
                for col in inspector.get_columns(name)
            ],
            "primary_key": inspector.get_pk_constraint(name),
            "foreign_keys": foreign_keys,
            "unique_constraints": inspector.get_unique_constraints(name),
            "record_count": connection.scalar(select(func.count()).select_from(table)),
        })
        nodes.append({"id": name, "data": {"label": name},
                      "position": {"x": (index % 3) * 220, "y": (index // 3) * 100}})
        for key_index, key in enumerate(foreign_keys):
            edges.append({
                "id": f"{name}:{key_index}",
                "source": name,
                "target": key["referred_table"],
                "data": {
                    "kind": "declared",
                    "source_columns": key["constrained_columns"],
                    "target_columns": key["referred_columns"],
                    "target_schema": key["referred_schema"],
                },
            })
    return {"tables": tables}, {"nodes": nodes, "edges": edges}
