import os

from pymongo.operations import SearchIndexModel

from app.src.domain.link import Link
from app.src.services.db_service import DBService
from app.src.services.logging_service import LoggingService

#import chromadb
import requests
from sentence_transformers import SentenceTransformer

from dotenv import load_dotenv
load_dotenv()
IMIS = os.getenv('IMIS')

class SemanticSearchService:
    def __init__(self, db_service: DBService, logging_service: LoggingService):
        self.db_service = db_service
        self.logging_service = logging_service
        self.model = SentenceTransformer("nomic-ai/nomic-embed-text-v1", trust_remote_code=True)
        self.initialize_embeddings()
        self.create_search_index()

    def get_embedding(self, data, precision="float32"):
        return self.model.encode(data, precision=precision).tolist()

    def initialize_embeddings(self):
        docs = []
        data = []
        embeddings = []
        result = requests.get(IMIS)
        publications = result.json()
        for publication in publications:
            data.append(publication['StandardTitle'])
            embeddings.append(self.get_embedding(publication['StandardTitle']))

        for i, (embedding, title) in enumerate(zip(embeddings, data)):
            doc = {
                "_id": i,
                "title": title,
                "embedding": embedding,
            }
            docs.append(doc)
        self.db_service.set_collection("embeddings")
        self.db_service.insert_many(docs)

    def create_search_index(self):
        search_index_model = SearchIndexModel(
            definition={
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "similarity": "dotProduct",
                        "numDimensions": 768
                    }
                ]
            },
            name="vector_index",
            type="vectorSearch"
        )
        self.db_service.set_collection("embeddings")
        self.db_service.create_search_index(model=search_index_model)



    def get_unprocessed_ids(self):
        where = {"link.is_DOI_success": False, "link.is_processed": False}
        what = {"_id": 1}
        self.db_service.set_collection("search_results")
        unprocessed_ids = self.db_service.select_what_where(what, where)
        return unprocessed_ids

    def get_current_link(self, search_result_id):
        self.db_service.set_collection("search_results")
        result = self.db_service.select_one(search_result_id)
        current_link = Link(result["link"]["url"], result["link"]["location_replace_url"], result["link"]["response_code"], result["link"]["response_type"], result["link"]["is_accepted_type"], result["link"]["DOI"], result["link"]["log_message"], result["link"]["is_DOI_success"], result["link"]["is_processed"])
        return current_link

    def get_title(self, search_result_id):
        where = {"_id": search_result_id}
        what = {"title": 1, "_id": 0}
        self.db_service.set_collection("search_results")
        title_cursor = self.db_service.select_what_where(what, where)
        title = title_cursor.next()
        title_cursor.close()
        return title['title']

    def do_semantic_search(self, title):
        query_embedding = self.get_embedding(title)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "queryVector": query_embedding,
                    "path": "embedding",
                    "exact": True,
                    "limit": 5
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "title": 1,
                    "score": {
                        "$meta": "vectorSearchScore"
                    }
                }
            }
        ]
        self.db_service.set_collection("embeddings")
        result = self.db_service.aggregate(pipeline)
        score = 0
        score_set = False
        for score_record in result:
            if not score_set:
                score = score_record["score"]
                score_set = True

        return score

    def convert_distance_to_score(self, distance):
        score = distance
        return score