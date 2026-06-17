# AI Router Benchmark Sandbox
# 构建：docker build -t airouter-benchmark:v1.0 -f infra/sandbox/Dockerfile infra/sandbox/
#
# 安全约束：
# - python:3.11-slim（最小攻击面）
# - 仅安装 pytest + numpy + pandas（harness 测试所需）
# - 运行时由调用方注入 --network none --user nobody --cap-drop ALL

FROM python:3.11-slim

RUN pip install --no-cache-dir pytest numpy pandas

# 创建 nobody 用户的 home 目录（容器 --user nobody 需要）
RUN mkdir -p /home/nobody && chown nobody:nogroup /home/nobody

WORKDIR /workspace
