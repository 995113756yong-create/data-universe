FROM flink:1.18.1-scala_2.12-java11
# Kafka SQL connector 版本必须与 Flink 1.18 匹配。
# ADD 从 URL 下载的文件权限是 600，flink 用户读不到，所以必须 chmod。
ADD https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.2.0-1.18/flink-sql-connector-kafka-3.2.0-1.18.jar /opt/flink/lib/
RUN chmod 644 /opt/flink/lib/flink-sql-connector-kafka-*.jar

# 用完整 table planner 替换 planner-loader，规避 FLINK-28693：
# watermark 定义在计算列上时，planner-loader 的类加载隔离会导致运行时代码生成失败。
RUN mv /opt/flink/lib/flink-table-planner-loader-*.jar /opt/flink/opt/ \
 && mv /opt/flink/opt/flink-table-planner_2.12-*.jar /opt/flink/lib/

# 预建 checkpoint/savepoint 目录并交给 flink 用户：
# 命名卷首次挂载时会继承镜像内目录的属主，否则 flink 用户无写权限。
RUN mkdir -p /opt/flink/checkpoints /opt/flink/savepoints \
 && chown -R flink:flink /opt/flink/checkpoints /opt/flink/savepoints
