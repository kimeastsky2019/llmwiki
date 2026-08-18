"""온톨로지 그래프 조회 서비스."""
from rdflib import Graph


class OntologyService:
    """SPARQL 로 온톨로지를 조회한다."""

    def __init__(self, path: str):
        self.graph = Graph()
        self.graph.parse(path)

    def list_classes(self):
        """정의된 클래스 목록."""
        query = """
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT ?cls ?label WHERE {
            ?cls a owl:Class .
            OPTIONAL { ?cls rdfs:label ?label }
        }
        """
        return list(self.graph.query(query))

    def register_asset(self, uri: str, label: str):
        """자산 인스턴스를 등록한다."""
        return self.graph.update(
            f"""
            PREFIX ex: <http://example.org/energy#>
            INSERT DATA {{
                <{uri}> a ex:EnergyAsset ; rdfs:label "{label}" .
            }}
            """
        )
