from silo.silo_package import SiloPackage
import xxhash

def make_build_hash(package: SiloPackage):
    hash = xxhash.xxh128()
    hash.update(package._source.encode())
    hash.update(package.options.model_dump_json().encode())
    for dep in package._dependencies:
        hash.update(dep.model_dump_json().encode())

    return hash.hexdigest()
    