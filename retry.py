"""One polite attempt to create the free Oracle A1 server (hermes-server).

Runs from GitHub Actions on a schedule. Each run makes at most one launch
request, with the SDK's automatic retries turned off. Prints SUCCESS / EXISTS /
WAIT and writes `result=<value>` to GITHUB_OUTPUT so the workflow can react.
"""
import json
import os
import sys

import oci

SERVER_NAME = "hermes-server"
SUBNET_NAME = "hermes-subnet"
SHAPE = "VM.Standard.A1.Flex"
OCPUS = float(os.environ.get("A1_OCPUS", "1"))
MEMORY_GB = float(os.environ.get("A1_MEMORY_GB", "6"))


def set_output(result: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"result={result}\n")
    print(f"RESULT: {result}")


def main() -> int:
    config = {
        "user": os.environ["OCI_USER"],
        "tenancy": os.environ["OCI_TENANCY"],
        "fingerprint": os.environ["OCI_FINGERPRINT"],
        "key_content": os.environ["OCI_KEY"],
        "region": os.environ.get("OCI_REGION", "ap-hyderabad-1"),
    }
    oci.config.validate_config(config)
    no_retry = oci.retry.NoneRetryStrategy()
    compartment = config["tenancy"]

    compute = oci.core.ComputeClient(config, retry_strategy=no_retry)
    network = oci.core.VirtualNetworkClient(config, retry_strategy=no_retry)
    identity = oci.identity.IdentityClient(config, retry_strategy=no_retry)

    # Stop if ANY A1 server already exists, whatever its name (e.g. one made by hand in the
    # console). A second A1 server would go over the Always Free limit.
    instances = oci.pagination.list_call_get_all_results(compute.list_instances, compartment).data
    alive = [i for i in instances
             if i.shape == SHAPE and i.lifecycle_state not in ("TERMINATED", "TERMINATING")]
    if alive:
        print(f"An A1 server already exists ({alive[0].display_name}): {alive[0].lifecycle_state}")
        set_output("exists")
        return 0

    # Look up AD / subnet / image once and cache them (A1_CACHE), so each try is only 2 API calls.
    cache_path = os.environ.get("A1_CACHE")
    cached = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
    if cached:
        ad, subnet_id = cached["ad"], cached["subnet_id"]
        image_id, image_name = cached["image_id"], cached["image_name"]
    else:
        ad = identity.list_availability_domains(compartment).data[0].name

        subnets = [s for s in network.list_subnets(compartment).data if s.display_name == SUBNET_NAME]
        if not subnets:
            print(f"Subnet {SUBNET_NAME} not found")
            return 1
        subnet_id = subnets[0].id

        images = compute.list_images(
            compartment,
            operating_system="Canonical Ubuntu",
            operating_system_version="24.04",
            shape=SHAPE,
            sort_by="TIMECREATED",
            sort_order="DESC",
        ).data
        if not images:
            print("No Ubuntu 24.04 ARM image found")
            return 1
        image_id, image_name = images[0].id, images[0].display_name
        if cache_path:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"ad": ad, "subnet_id": subnet_id, "image_id": image_id,
                           "image_name": image_name}, f)

    with open(os.path.join(os.path.dirname(__file__), "hermes_key.pub"), encoding="utf-8") as f:
        ssh_key = f.read().strip()

    details = oci.core.models.LaunchInstanceDetails(
        compartment_id=compartment,
        availability_domain=ad,
        display_name=SERVER_NAME,
        shape=SHAPE,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=OCPUS, memory_in_gbs=MEMORY_GB
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=image_id),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet_id, assign_public_ip=True
        ),
        metadata={"ssh_authorized_keys": ssh_key},
    )

    print(f"Trying {SHAPE} {OCPUS:g} OCPU / {MEMORY_GB:g} GB in {ad} with {image_name}")
    try:
        result = compute.launch_instance(details).data
    except oci.exceptions.ServiceError as e:
        print(f"Not yet: {e.status} {e.code} - {e.message}")
        if e.status == 429:
            set_output("toomany")
            return 0
        if e.status in (500, 503) or "capacity" in str(e.message).lower():
            set_output("wait")
            return 0
        return 1  # anything else (bad config, limits) should fail loudly

    print(f"SUCCESS: {result.display_name} {result.id} {result.lifecycle_state}")
    set_output("success")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except oci.exceptions.ServiceError as err:
        if err.status == 429:  # rate limited during a lookup: back off, don't fail
            print(f"Not yet: 429 {err.code} - {err.message}")
            set_output("toomany")
            sys.exit(0)
        raise
