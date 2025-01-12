from . import generate_k8s_source


def rules():
    return (*generate_k8s_source.rules(),)
