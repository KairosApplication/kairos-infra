#!/usr/bin/env bash
set -euo pipefail
: "${AWS_REGION:?Defina AWS_REGION}"
: "${EKS_CLUSTER_NAME:?Defina EKS_CLUSTER_NAME}"
cd "$(dirname "$0")/.."

aws eks update-kubeconfig --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME"
python3 scripts/bootstrap-namespaces.py | kubectl apply -f -
kubectl apply -f platform/ingress-class.yaml
kubectl apply -f platform/enable-network-policy.yaml

helm repo add aws-secrets-manager https://aws.github.io/secrets-store-csi-driver-provider-aws --force-update
helm repo update aws-secrets-manager
helm upgrade --install aws-secrets-provider \
  aws-secrets-manager/secrets-store-csi-driver-provider-aws \
  --version 3.1.4 --namespace kube-system \
  -f platform/secrets-values.yaml --wait --timeout 10m

kubectl get csidriver secrets-store.csi.k8s.io
kubectl wait --for=condition=Established crd/secretproviderclasses.secrets-store.csi.x-k8s.io --timeout=120s
python3 scripts/bootstrap-rbac.py | kubectl apply -f -
kubectl get ingressclass kairos-public
