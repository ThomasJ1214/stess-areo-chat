"""Register frozen CUDA resources before the application imports native modules."""
from rocket_workbench.bundled_cuda import configure_bundled_cuda

configure_bundled_cuda()
