import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.configuration import load_config, build_criteria, validate_config

EXAMPLE = Path(__file__).resolve().parents[1] / 'config.example.yaml'


class ConfigurationTests(unittest.TestCase):
    def test_generic_defaults_have_no_personal_profile(self):
        config = load_config(EXAMPLE)
        text = build_criteria(config)
        self.assertIn('software development', text)
        self.assertNotIn('Target start date:', text)
        self.assertEqual(config['blacklist']['companies'], [])
        self.assertEqual(config['sources'], ['linkedin'])

    def test_arbitrary_profession_and_dates(self):
        config = load_config(EXAMPLE)
        config['criteria']['required'] = ['The role must involve architecture.']
        config['target'] = {'start_date':'2030-01-01','end_date':'2030-12-31','missing_date':'flexible'}
        validate_config(config)
        text = build_criteria(config)
        self.assertIn('architecture', text)
        self.assertNotIn('software development', text)
        self.assertIn('2030-01-01', text)
        self.assertIn('flexible', text)

    def test_explicit_config_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'JOBFINDER_CONFIG':str(Path(directory)/'missing.yaml')}):
            self.assertEqual(load_config(EXAMPLE)['sources'], ['linkedin'])
            with self.assertRaises(FileNotFoundError):
                load_config()

    def test_invalid_configuration(self):
        for update in ({'sources':['unknown']},{'search_profiles':[]}, {'criteria':{}},
                       {'target':{'start_date':'2030-12-01','end_date':'2030-01-01'}}):
            config=load_config(EXAMPLE)
            config.update(update)
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_apec_does_not_default_to_internships(self):
        from src.scrapers.apec import ApecScraper
        self.assertIsNone(ApecScraper().contract_filter)
        self.assertEqual(ApecScraper(contract_filter='example').contract_filter,'example')
