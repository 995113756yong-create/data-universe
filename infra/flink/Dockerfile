FROM flink:1.18.1-scala_2.12-java11
# Kafka SQL connector 版本必须与 Flink 1.18 匹配。
# ADD 从 URL 下载的文件权限是 600，flink 用户读不到，所以必须 chmod。
ADD https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.2.0-1.18/flink-sql-connector-kafka-3.2.0-1.18.jar /opt/flink/lib/
RUN chmod 644 /opt/flink/lib/flink-sql-connector-kafka-*.jar
