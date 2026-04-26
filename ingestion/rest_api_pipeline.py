import dlt
from dlt.sources.rest_api import (
    check_connection,
    rest_api_source,
)


def load_pokemon(base_url: str = "https://pokeapi.co/api/v2/") -> None:
    pipeline = dlt.pipeline(
        pipeline_name="rest_api_pokemon",
        destination="filesystem",
        dataset_name="rest_api_data",
    )

    pokemon_source = rest_api_source(
        {
            "client": {
                "base_url": base_url,
                # If you leave out the paginator, it will be inferred from the API:
                # "paginator": "json_link",
            },
            "resource_defaults": {
                "endpoint": {
                    "params": {
                        "limit": 1000,
                    },
                },
            },
            "resources": [
                "pokemon",
                "berry",
                "location",
            ],
        },
        name="pokemon",
    )

    def check_network_and_authentication() -> None:
        (can_connect, error_msg) = check_connection(
            pokemon_source,
            "not_existing_endpoint",
        )
        if not can_connect:
            pass  # do something with the error message

    check_network_and_authentication()

    load_info = pipeline.run(pokemon_source)
    print(load_info)  # noqa: T201


if __name__ == "__main__":
    load_pokemon()
