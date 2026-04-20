"""
Hindsight Vectorize: Vector-based patient data storage and similarity learning
Efficiently stores patient records as vectors and learns from historical patient data
"""

import json
import numpy as np
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.decomposition import PCA
import pickle


VECTORSTORE_DB_PATH = Path("vectorstore.db")
VECTOR_CACHE_PATH = Path("vector_cache.pkl")
MIN_PATIENTS_FOR_LEARNING = 5


class HindsightVectorizer:
    """Converts patient data into efficient vector representations"""
    
    def __init__(self):
        self.scaler = StandardScaler()
        self.pca = None
        self.is_fitted = False
        self.feature_names = []
        
    def fit(self, data: np.ndarray, feature_names: List[str] = None):
        """Fit the vectorizer on training data"""
        if len(data) > 0:
            self.scaler.fit(data)
            self.feature_names = feature_names or [f"feature_{i}" for i in range(data.shape[1])]
            self.is_fitted = True
            
    def transform(self, data: Dict) -> np.ndarray:
        """Convert patient data dictionary to vector"""
        if not self.is_fitted and len(data) > 0:
            self.fit(np.array([list(data.values())]))
        
        vector = np.array([list(data.values())], dtype=float)
        normalized = self.scaler.transform(vector)
        return normalized.flatten()
    
    def apply_dimensionality_reduction(self, vectors: np.ndarray, n_components: int = None) -> np.ndarray:
        """Reduce vector dimensions while preserving patterns"""
        if vectors.shape[0] < 2:
            return vectors
        
        n_comp = min(n_components or max(2, vectors.shape[1] // 2), vectors.shape[0] - 1, vectors.shape[1])
        self.pca = PCA(n_components=n_comp)
        return self.pca.fit_transform(vectors)
    
    def inverse_transform(self, vectors: np.ndarray) -> np.ndarray:
        """Convert vectors back to original space"""
        if self.pca:
            vectors = self.pca.inverse_transform(vectors)
        return self.scaler.inverse_transform(vectors)


class VectorStore:
    """Efficient storage and retrieval of patient vectors with similarity search"""
    
    def __init__(self):
        self.initialize_db()
        self.vectorizer = HindsightVectorizer()
        self.vector_cache = {}
        self.load_cache()
        
    def initialize_db(self):
        """Create database schema for vector storage"""
        with sqlite3.connect(VECTORSTORE_DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patient_vectors (
                    patient_id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    timestamp TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    diagnosis_result REAL,
                    visit_count INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vector_insights (
                    insight_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id TEXT,
                    insight_type TEXT,
                    insight_data TEXT,
                    created_at TEXT,
                    FOREIGN KEY(patient_id) REFERENCES patient_vectors(patient_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS similar_patterns (
                    pattern_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id_1 TEXT,
                    patient_id_2 TEXT,
                    similarity_score REAL,
                    shared_risk_factors TEXT,
                    created_at TEXT,
                    FOREIGN KEY(patient_id_1) REFERENCES patient_vectors(patient_id),
                    FOREIGN KEY(patient_id_2) REFERENCES patient_vectors(patient_id)
                )
            """)
            conn.commit()
    
    def store_patient_vector(self, patient_id: str, data: Dict, diagnosis_result: float = None):
        """Store patient data as a vector"""
        vector = self.vectorizer.transform(data)
        vector_bytes = pickle.dumps(vector)
        timestamp = datetime.now().isoformat()
        data_json = json.dumps(data)
        
        with sqlite3.connect(VECTORSTORE_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO patient_vectors 
                (patient_id, vector, timestamp, data_json, diagnosis_result, visit_count)
                VALUES (?, ?, ?, ?, ?, 
                    COALESCE((SELECT visit_count + 1 FROM patient_vectors WHERE patient_id = ?), 1))
            """, (patient_id, vector_bytes, timestamp, data_json, diagnosis_result, patient_id))
            conn.commit()
        
        self.vector_cache[patient_id] = vector
        self.save_cache()
        
    def get_patient_vector(self, patient_id: str) -> Tuple[np.ndarray, Dict]:
        """Retrieve patient vector and original data"""
        if patient_id in self.vector_cache:
            vector = self.vector_cache[patient_id]
        else:
            with sqlite3.connect(VECTORSTORE_DB_PATH) as conn:
                cursor = conn.cursor()
                result = cursor.execute(
                    "SELECT vector, data_json FROM patient_vectors WHERE patient_id = ?",
                    (patient_id,)
                ).fetchone()
            
            if result:
                vector = pickle.loads(result[0])
                data = json.loads(result[1])
                self.vector_cache[patient_id] = vector
                return vector, data
            return None, None
        
        with sqlite3.connect(VECTORSTORE_DB_PATH) as conn:
            result = conn.execute(
                "SELECT data_json FROM patient_vectors WHERE patient_id = ?",
                (patient_id,)
            ).fetchone()
        
        data = json.loads(result[0]) if result else {}
        return vector, data
    
    def similarity_search(self, patient_id: str, top_k: int = 5) -> List[Tuple[str, float, Dict]]:
        """Find similar patients based on vector similarity"""
        query_vector, _ = self.get_patient_vector(patient_id)
        if query_vector is None:
            return []
        
        all_vectors = self._get_all_vectors()
        if not all_vectors:
            return []
        
        similarities = []
        for pid, vector in all_vectors.items():
            if pid != patient_id:
                similarity = self._cosine_similarity(query_vector, vector)
                similarities.append((pid, similarity))
        
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        results = []
        for pid, score in similarities[:top_k]:
            _, data = self.get_patient_vector(pid)
            results.append((pid, score, data))
        
        return results
    
    def learn_patterns(self) -> Dict:
        """Learn patterns from all stored patient vectors"""
        all_vectors = self._get_all_vectors()
        
        if len(all_vectors) < MIN_PATIENTS_FOR_LEARNING:
            return {"status": "insufficient_data", "count": len(all_vectors)}
        
        vectors_array = np.array([v for v in all_vectors.values()])
        
        # Calculate statistics
        mean_vector = np.mean(vectors_array, axis=0)
        std_vector = np.std(vectors_array, axis=0)
        
        # Find high-risk and low-risk patterns
        high_risk_vector = np.percentile(vectors_array, 75, axis=0)
        low_risk_vector = np.percentile(vectors_array, 25, axis=0)
        
        patterns = {
            "mean_patient_profile": mean_vector.tolist(),
            "risk_variation": std_vector.tolist(),
            "high_risk_pattern": high_risk_vector.tolist(),
            "low_risk_pattern": low_risk_vector.tolist(),
            "total_patients": len(all_vectors),
            "learned_at": datetime.now().isoformat()
        }
        
        # Find similar patient clusters
        clustering_insights = self._identify_patient_clusters(vectors_array, list(all_vectors.keys()))
        patterns["clusters"] = clustering_insights
        
        return patterns
    
    def _get_all_vectors(self) -> Dict[str, np.ndarray]:
        """Get all stored patient vectors"""
        vectors = {}
        
        with sqlite3.connect(VECTORSTORE_DB_PATH) as conn:
            cursor = conn.cursor()
            results = cursor.execute(
                "SELECT patient_id, vector FROM patient_vectors"
            ).fetchall()
        
        for patient_id, vector_bytes in results:
            vectors[patient_id] = pickle.loads(vector_bytes)
        
        return vectors
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors"""
        dot_product = np.dot(vec1, vec2)
        norm_vec1 = np.linalg.norm(vec1)
        norm_vec2 = np.linalg.norm(vec2)
        
        if norm_vec1 == 0 or norm_vec2 == 0:
            return 0.0
        
        return dot_product / (norm_vec1 * norm_vec2)
    
    def _identify_patient_clusters(self, vectors: np.ndarray, patient_ids: List[str]) -> List[Dict]:
        """Identify clusters of similar patients"""
        if len(vectors) < 3:
            return []
        
        # Simple clustering based on vector similarity
        clusters = []
        clustered_patients = set()
        
        for i, patient_id in enumerate(patient_ids):
            if patient_id in clustered_patients:
                continue
            
            cluster = [patient_id]
            clustered_patients.add(patient_id)
            
            for j, other_id in enumerate(patient_ids):
                if i != j and other_id not in clustered_patients:
                    similarity = self._cosine_similarity(vectors[i], vectors[j])
                    if similarity > 0.7:
                        cluster.append(other_id)
                        clustered_patients.add(other_id)
            
            if len(cluster) > 1:
                clusters.append({
                    "patient_ids": cluster,
                    "size": len(cluster),
                    "commonality": "high_similarity"
                })
        
        return clusters
    
    def get_patient_insights(self, patient_id: str) -> Dict:
        """Get learning insights specific to a patient"""
        vector, data = self.get_patient_vector(patient_id)
        if vector is None:
            return {}
        
        # Get similar patients
        similar = self.similarity_search(patient_id, top_k=3)
        
        # Get population patterns
        patterns = self.learn_patterns()
        
        # Calculate risk percentile
        all_vectors = self._get_all_vectors()
        if all_vectors:
            vectors_array = np.array([v for v in all_vectors.values()])
            # Use first feature as proxy for risk assessment
            patient_val = vector[0] if len(vector) > 0 else 0
            percentile = np.percentile(vectors_array[:, 0] if vectors_array.shape[1] > 0 else [], patient_val)
        else:
            percentile = 50
        
        insights = {
            "patient_id": patient_id,
            "risk_percentile": float(percentile),
            "similar_patients": [
                {"id": pid, "similarity": float(sim), "data": pdata}
                for pid, sim, pdata in similar
            ],
            "population_mean": patterns.get("mean_patient_profile", []),
            "clusters": patterns.get("clusters", []),
            "retrieved_at": datetime.now().isoformat()
        }
        
        return insights
    
    def save_cache(self):
        """Save vector cache to disk"""
        try:
            with open(VECTOR_CACHE_PATH, 'wb') as f:
                pickle.dump(self.vector_cache, f)
        except Exception as e:
            print(f"Error saving cache: {e}")
    
    def load_cache(self):
        """Load vector cache from disk"""
        try:
            if VECTOR_CACHE_PATH.exists():
                with open(VECTOR_CACHE_PATH, 'rb') as f:
                    self.vector_cache = pickle.load(f)
        except Exception as e:
            print(f"Error loading cache: {e}")
    
    def get_all_patients_summary(self) -> List[Dict]:
        """Get summary of all stored patients"""
        with sqlite3.connect(VECTORSTORE_DB_PATH) as conn:
            cursor = conn.cursor()
            results = cursor.execute("""
                SELECT patient_id, timestamp, diagnosis_result, visit_count, data_json
                FROM patient_vectors
                ORDER BY timestamp DESC
            """).fetchall()
        
        summary = []
        for patient_id, timestamp, diagnosis, visits, data_json in results:
            data = json.loads(data_json)
            summary.append({
                "patient_id": patient_id,
                "timestamp": timestamp,
                "diagnosis_result": diagnosis,
                "visit_count": visits,
                "age": data.get("age", "N/A"),
                "sex": data.get("sex", "N/A")
            })
        
        return summary


# Global vectorstore instance
_vectorstore = None

def get_vectorstore() -> VectorStore:
    """Get or create global vectorstore instance"""
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = VectorStore()
    return _vectorstore
