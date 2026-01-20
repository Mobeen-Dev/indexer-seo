docker run -d   --name redis-stack   -p 127.0.0.1:6379:6379   -p 127.0.0.1:8001:8001   -v redis_data:/data   -e REDIS_ARGS="--requirepass strongpassword123 --appendonly yes "   redis/redis-stack:7.4.0-v8


