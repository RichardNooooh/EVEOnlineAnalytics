"""Read retained reference data and parse manufacturing recipes."""

import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

REFERENCE_ARCHIVE_DIRECTORY = Path(".local/data/raw/everef/reference-data/objects")
REFERENCE_ARCHIVE_SUFFIX = "_reference-data-latest.tar.xz"
REFERENCE_ARCHIVE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def find_repo_root(start_path=None):
    start = Path.cwd() if start_path is None else Path(start_path)
    for path in (start, *start.parents):
        if (path / "transformation" / "dbt_project.yml").is_file():
            return path
    raise FileNotFoundError("Could not locate the repository root containing transformation/dbt_project.yml.")


def retained_reference_archive(repo_root=None):
    root = find_repo_root() if repo_root is None else Path(repo_root)
    archive_directory = root / REFERENCE_ARCHIVE_DIRECTORY
    candidates = []
    for archive_path in archive_directory.rglob(f"*{REFERENCE_ARCHIVE_SUFFIX}"):
        if not archive_path.is_file():
            continue
        timestamp_text, separator, _ = archive_path.name.partition("__")
        if separator != "__" or len(timestamp_text) != 16:  # expected length of timestamp text
            continue
        try:
            parsed_timestamp = datetime.strptime(timestamp_text, REFERENCE_ARCHIVE_TIMESTAMP_FORMAT)
        except ValueError:
            continue
        if parsed_timestamp.strftime(REFERENCE_ARCHIVE_TIMESTAMP_FORMAT) != timestamp_text:
            continue
        candidates.append((timestamp_text, str(archive_path), archive_path))

    if not candidates:
        raise FileNotFoundError(
            f"No retained reference archive found under {archive_directory}. "
            "Run the reference ingestion workflow to retain a "
            "*_reference-data-latest.tar.xz archive before running this notebook."
        )

    _, _, archive_path = max(candidates)
    acquisition_timestamp = datetime.strptime(
        archive_path.name.partition("__")[0], REFERENCE_ARCHIVE_TIMESTAMP_FORMAT
    ).replace(tzinfo=UTC)
    return archive_path, acquisition_timestamp


def load_reference_records(archive_path):
    blueprints = None
    reference_types = None
    meta_groups = None
    with tarfile.open(archive_path, mode="r:xz") as archive:
        for member in archive:
            member_name = member.name.removeprefix("./")
            if member_name not in {"blueprints.json", "types.json", "meta_groups.json"} or not member.isfile():
                continue
            reference_file = archive.extractfile(member)
            if reference_file is None:
                raise ValueError(f"Reference extract could not read {member_name}.")
            with reference_file:
                reference_data = json.load(reference_file)
            if member_name == "blueprints.json":
                blueprints = reference_data
            elif member_name == "types.json":
                reference_types = reference_data
            else:
                meta_groups = reference_data

    if not isinstance(blueprints, dict) or not blueprints:
        raise ValueError("Reference extract must contain a nonempty blueprints.json object.")
    if not isinstance(reference_types, dict) or not reference_types:
        raise ValueError("Reference extract must contain a nonempty types.json object.")
    if not isinstance(meta_groups, dict) or not meta_groups:
        raise ValueError("Reference extract must contain a nonempty meta_groups.json object.")
    return blueprints, reference_types, meta_groups


def manufacturing_products(blueprints):
    """Return product IDs and blueprint IDs missing manufacturing products."""
    product_ids = set()
    blueprints_without_products = []

    for blueprint_id, blueprint in blueprints.items():
        if not isinstance(blueprint, dict) or not isinstance(blueprint.get("activities"), dict):
            raise ValueError(f"Invalid activities for blueprint {blueprint_id}.")
        activities = blueprint["activities"]

        # some listed blueprints are only used for *inventing* a new blueprint (i.e. Tech II blueprints), among other things
        if "manufacturing" not in activities:
            continue
        manufacturing = activities["manufacturing"]
        if not isinstance(manufacturing, dict):
            raise ValueError(f"Invalid manufacturing products for blueprint {blueprint_id}.")
        products = manufacturing.get("products")

        if products is None or products == {}:
            blueprints_without_products.append(int(blueprint_id))
            continue
        if not isinstance(products, dict):
            raise ValueError(f"Invalid manufacturing products for blueprint {blueprint_id}.")
        for product_key, product in products.items():
            type_id = product.get("type_id") if isinstance(product, dict) else None
            if type(type_id) is not int or type_id <= 0 or str(type_id) != product_key:
                raise ValueError(f"Invalid product {product_key} for blueprint {blueprint_id}.")
            product_ids.add(type_id)

    if not product_ids:
        raise ValueError("No manufacturing products found in the reference extract.")

    return product_ids, blueprints_without_products


def manufacturing_links(blueprints, reference_types):
    links_by_pair = {}

    for blueprint_key in sorted(blueprints, key=int):
        blueprint_id = int(blueprint_key)
        blueprint = blueprints[blueprint_key]
        blueprint_type = reference_types.get(str(blueprint_id))
        if not isinstance(blueprint_type, dict) or blueprint_type.get("published") is not True:
            continue
        if not isinstance(blueprint, dict) or not isinstance(blueprint.get("activities"), dict):
            raise ValueError(f"Invalid activities for blueprint {blueprint_id}.")
        manufacturing = blueprint["activities"].get("manufacturing")
        if manufacturing is None:
            continue
        if not isinstance(manufacturing, dict):
            raise ValueError(f"Invalid manufacturing activity for blueprint {blueprint_id}.")
        materials = manufacturing.get("materials")
        products = manufacturing.get("products")
        if materials is None or materials == {} or products is None or products == {}:
            continue
        if not isinstance(materials, dict) or not isinstance(products, dict):
            raise ValueError(f"Invalid manufacturing recipe for blueprint {blueprint_id}.")

        inputs = []
        for material_key, material in materials.items():
            input_type_id = material.get("type_id") if isinstance(material, dict) else None
            input_quantity = material.get("quantity") if isinstance(material, dict) else None
            if (
                type(input_type_id) is not int
                or input_type_id <= 0
                or str(input_type_id) != material_key
                or type(input_quantity) is not int
                or input_quantity <= 0
            ):
                raise ValueError(f"Invalid material {material_key} for blueprint {blueprint_id}.")
            inputs.append((input_type_id, input_quantity))

        outputs = []
        for product_key, product in products.items():
            output_type_id = product.get("type_id") if isinstance(product, dict) else None
            output_quantity = product.get("quantity") if isinstance(product, dict) else None
            if (
                type(output_type_id) is not int
                or output_type_id <= 0
                or str(output_type_id) != product_key
                or type(output_quantity) is not int
                or output_quantity <= 0
            ):
                raise ValueError(f"Invalid product {product_key} for blueprint {blueprint_id}.")
            outputs.append((output_type_id, output_quantity))

        for input_type_id, input_quantity in inputs:
            for output_type_id, output_quantity in outputs:
                pair = (input_type_id, output_type_id)
                recipe = (input_quantity, output_quantity)
                previous_recipe = links_by_pair.get(pair)
                if previous_recipe is not None:
                    if previous_recipe != recipe:
                        raise ValueError(f"Conflicting manufacturing recipes for {input_type_id} -> {output_type_id}.")
                    raise ValueError(f"Duplicate manufacturing recipe for {input_type_id} -> {output_type_id}.")
                links_by_pair[pair] = recipe

    return pl.DataFrame(
        [
            {
                "input_type_id": input_type_id,
                "output_type_id": output_type_id,
                "input_quantity": input_quantity,
                "output_quantity": output_quantity,
            }
            for (input_type_id, output_type_id), (input_quantity, output_quantity) in sorted(links_by_pair.items())
        ],
        schema={
            "input_type_id": pl.Int64,
            "output_type_id": pl.Int64,
            "input_quantity": pl.Int64,
            "output_quantity": pl.Int64,
        },
    )
