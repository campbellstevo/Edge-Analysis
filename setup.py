from setuptools import setup, find_packages

setup(
    name="edge_analysis",
    version="1.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        # Your requirements will be read from requirements.txt
    ],
)
