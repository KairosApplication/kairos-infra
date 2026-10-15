# Build executado apos a CI da API; nao inclui .env nem arquivos locais.
FROM eclipse-temurin:21-jdk-jammy AS build
WORKDIR /workspace
COPY .mvn/ .mvn/
COPY mvnw pom.xml ./
RUN chmod +x mvnw
COPY src/ src/
RUN ./mvnw --batch-mode --no-transfer-progress -DskipTests package && \
    mkdir -p /out && \
    find target -maxdepth 1 -name '*.jar' ! -name '*-plain.jar' -exec cp {} /out/app.jar \;

FROM eclipse-temurin:21-jre-jammy
RUN groupadd --gid 10001 kairos && \
    useradd --uid 10001 --gid 10001 --no-create-home kairos
WORKDIR /app
COPY --from=build --chown=10001:10001 /out/app.jar ./app.jar
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
