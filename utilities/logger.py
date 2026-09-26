"""
Module de logging structuré pour Cloud Logging
Utilise le format JSON pour une meilleure intégration avec Google Cloud Logging
"""
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional

class StructuredLogger:
    """
    Logger structuré qui produit des logs au format JSON
    Compatible avec Google Cloud Logging
    """
    
    @staticmethod
    def _log(level: str, message: str, **kwargs):
        """
        Crée un log structuré au format JSON
        
        Args:
            level: Niveau de log (INFO, WARNING, ERROR, CRITICAL)
            message: Message principal
            **kwargs: Métadonnées supplémentaires
        """
        # Filtrer et sérialiser les kwargs pour éviter les problèmes de sérialisation JSON
        serializable_kwargs = {}
        for key, value in kwargs.items():
            # Si la valeur est une Exception, la convertir en dict
            if isinstance(value, Exception):
                serializable_kwargs[key] = {
                    'error_type': type(value).__name__,
                    'error_message': str(value),
                }
            # Si la valeur est sérialisable JSON, l'ajouter directement
            else:
                try:
                    # Tester si la valeur est sérialisable
                    json.dumps(value)
                    serializable_kwargs[key] = value
                except (TypeError, ValueError):
                    # Si non sérialisable, convertir en string
                    serializable_kwargs[key] = str(value)
        
        log_entry = {
            'severity': level,
            'message': message,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            **serializable_kwargs
        }
        
        # Écrire en JSON sur stdout (Cloud Logging lit depuis stdout)
        print(json.dumps(log_entry), file=sys.stdout, flush=True)
    
    @staticmethod
    def info(message: str, **kwargs):
        """Log au niveau INFO"""
        StructuredLogger._log('INFO', message, **kwargs)
    
    @staticmethod
    def warning(message: str, error: Optional[Exception] = None, **kwargs):
        """Log au niveau WARNING"""
        # Extraire 'error' de kwargs s'il existe (pour éviter la duplication)
        if 'error' in kwargs and isinstance(kwargs['error'], Exception):
            # Si error est passé dans kwargs, l'utiliser et le retirer
            error = kwargs.pop('error')
        
        error_data = {}
        if error:
            error_data = {
                'error_type': type(error).__name__,
                'error_message': str(error),
            }
        StructuredLogger._log('WARNING', message, **error_data, **kwargs)
    
    @staticmethod
    def error(message: str, error: Optional[Exception] = None, **kwargs):
        """Log au niveau ERROR"""
        error_data = {}
        if error:
            error_data = {
                'error_type': type(error).__name__,
                'error_message': str(error),
            }
        StructuredLogger._log('ERROR', message, **error_data, **kwargs)
    
    @staticmethod
    def critical(message: str, error: Optional[Exception] = None, **kwargs):
        """Log au niveau CRITICAL"""
        error_data = {}
        if error:
            error_data = {
                'error_type': type(error).__name__,
                'error_message': str(error),
            }
        StructuredLogger._log('CRITICAL', message, **error_data, **kwargs)

# Instance globale du logger
logger = StructuredLogger()

