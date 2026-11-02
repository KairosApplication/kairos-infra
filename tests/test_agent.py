import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from sync_runtime import merge_agent_runtime, parse_agent_input
from registry import load_registry

class AgentTests(unittest.TestCase):
    def test_database_and_bearer_token_are_required_and_preserved(self):
        supplied={"MONGODB_URI":"mongodb+srv://test.example/kairos","API_ACCESS_TOKEN":"a"*48}
        result=merge_agent_runtime({},supplied,"b"*48)
        self.assertEqual(result["MONGODB_DATABASE"],"kairos")
        self.assertEqual(result["API_ACCESS_TOKEN"],"a"*48)
        self.assertEqual(merge_agent_runtime(result,{},"c"*48),result)
        for value in ({}, {"MONGODB_URI":"mongodb+srv://test.example"},
                      dict(supplied, API_ACCESS_TOKEN="short")):
            with self.assertRaises(ValueError):
                merge_agent_runtime({},value,"b"*48)

    def test_registry_separates_postgres_tests_from_mongodb_tests(self):
        registry=load_registry()
        self.assertEqual(registry["agent-api"]["source_repository"],"KairosApplication/kairos-api-ia")
        self.assertTrue(registry["agent-api"]["enabled"])
        self.assertEqual(registry["agent-api"]["build_kind"],"java21")
        self.assertEqual(registry["agent-api"].get("maven_test_profile",""),"")
        self.assertEqual(registry["mobile-api"]["maven_test_profile"],"postgres-tests")

    def test_pasted_uri_and_json_are_supported_without_disabling_tls(self):
        uri="mongodb+srv://test.example/?retryWrites=true"
        parsed=parse_agent_input(uri)
        self.assertEqual(parsed["MONGODB_DATABASE"],"kairos_ai")
        self.assertEqual(parse_agent_input(json.dumps(parsed)),parsed)
        for raw in ("not-a-uri", "[]", "{invalid}"):
            with self.assertRaises(ValueError):
                parse_agent_input(raw)
        for query in ("tls=false", "tlsInsecure=true", "tlsAllowInvalidCertificates=true"):
            with self.assertRaises(ValueError):
                merge_agent_runtime({}, {"MONGODB_URI":uri+"&"+query,"MONGODB_DATABASE":"kairos_ai"}, "b"*48)
