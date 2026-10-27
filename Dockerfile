# MCP server only, for directory checks (e.g. Glama): starts `novastudio mcp` on stdio so its tools can be listed.
# The supported way to run analyses is the Windows app (https://novasolver.jp/en/studio/); this image has no
# CalculiX, OpenFOAM or PyMeshLab, so STL remeshing and those engines report as unavailable.
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglu1-mesa libgl1 libxrender1 libxcursor1 libxft2 libxinerama1 \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "mcp>=2.3,<3" fastapi "uvicorn[standard]" numpy scipy matplotlib gmsh meshio psutil pyamg zstandard
WORKDIR /app
COPY backend/ /app/backend/
ENV PYTHONPATH=/app/backend
CMD ["python", "-m", "novastudio", "mcp"]
