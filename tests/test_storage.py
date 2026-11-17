import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from rf_updater import preferences, storage
from rf_updater.engine import Engine, exclusive, _process_image
from rf_updater.models import Cancelled, Release, UpdaterError, atomic_json


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rf-storage-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base/'data'
        self.root.mkdir()
        self.config = self.base/'settings/directories.json'
        self.preference_patch = patch('rf_updater.preferences.preferences_path', return_value=self.config)
        self.preference_patch.start()
        self.addCleanup(self.preference_patch.stop)
        self.engine = Engine(self.root, 'linux')
        self.old = self.generation('old', '00000001')
        self.previous = self.generation('previous', '00000002')
        self.active = self.generation('active', '00000003')
        self.write_state(self.active, self.previous)
        self.cache_key = self.cache('complete', b'archive-data', 12)
        self.partial_key = self.cache('partial', b'part', 100)
        (self.root/'cache/unrelated.txt').write_text('do not delete')

    def generation(self, tag, suffix):
        release = Release('linux', 'https://api.rocketfoundry.net/download/linux', 100, f'"{tag}"')
        name = f'{release.identity}-{suffix}'
        directory = self.root/'installs'/name
        (directory/'game').mkdir(parents=True)
        (directory/'game/RocketFoundry').write_bytes(b'game-'+tag.encode())
        value = {'generation':name, 'release':release.to_dict(), 'executable':'RocketFoundry',
                 'installed_at':'2026-11-16T08:00:00+00:00', 'package_sha256':'0'*64, 'publisher_checksum':False}
        atomic_json(directory/'receipt.json', {'installation':value, 'files':[]})
        return value

    def cache(self, tag, data, expected):
        release = Release('linux','https://api.rocketfoundry.net/download/linux',expected,f'"{tag}"')
        cache = self.root/'cache'
        cache.mkdir(exist_ok=True)
        (cache/f'{release.identity}.part').write_bytes(data)
        atomic_json(cache/f'{release.identity}.json',release.to_dict())
        return f'cache/{release.identity}'

    def write_state(self, active, previous):
        atomic_json(self.root/'state.json', {'schema':1,'active':active,'previous':previous})

    def inventory(self):
        return storage.scan(self.engine, threading.Event())

    def test_inventory_groups_sizes_and_protected_versions(self):
        inventory = self.inventory()
        by_key = {item.key:item for item in inventory.items}
        self.assertTrue(by_key[self.cache_key].deletable)
        self.assertEqual(by_key[self.cache_key].status,'下载完成（待校验）')
        self.assertEqual(by_key[self.partial_key].status,'下载未完成')
        self.assertFalse(by_key['installs/'+self.active['generation']].deletable)
        self.assertFalse(by_key['installs/'+self.previous['generation']].deletable)
        self.assertTrue(by_key['installs/'+self.old['generation']].deletable)
        self.assertFalse(by_key['cache/unrelated.txt'].deletable)
        self.assertGreater(inventory.disk_free,0)
        self.assertGreater(inventory.totals['cache'],len(b'archive-data'))
        self.assertGreater(inventory.totals['active'],0)

    def test_cleanup_removes_only_selected_cache_and_its_record(self):
        result = storage.cleanup(self.engine,[self.cache_key])
        identity = self.cache_key.split('/')[1]
        self.assertEqual(result.removed,1)
        self.assertFalse((self.root/'cache'/f'{identity}.part').exists())
        self.assertFalse((self.root/'cache'/f'{identity}.json').exists())
        self.assertTrue((self.root/'cache/unrelated.txt').exists())
        self.assertTrue((self.root/'cache'/f"{self.partial_key.split('/')[1]}.part").exists())
        self.assertEqual(self.engine.state()['active'],self.active)

    def test_old_install_requires_explicit_backup_acknowledgement(self):
        old_path = self.root/'installs'/self.old['generation']
        (old_path/'game/my-save.json').write_text('save')
        with self.assertRaisesRegex(UpdaterError,'备份'):
            storage.cleanup(self.engine,['installs/'+self.old['generation']])
        self.assertTrue((old_path/'game/my-save.json').exists())
        result=storage.cleanup(self.engine,['installs/'+self.old['generation']],allow_old=True)
        self.assertEqual(result.removed,1)
        self.assertFalse(old_path.exists())
        self.assertTrue((self.root/'installs'/self.active['generation']).exists())
        self.assertTrue((self.root/'installs'/self.previous['generation']).exists())

    def test_old_cleanup_refused_while_game_running(self):
        atomic_json(self.root/'game-session.json', {
            'pid': os.getpid(), 'executable': _process_image(os.getpid()) or str(Path(sys.executable).resolve()),
            'command': [sys.executable], 'generation': self.active['generation']})
        old_key = 'installs/' + self.old['generation']
        with self.assertRaisesRegex(UpdaterError, '运行'):
            storage.cleanup(self.engine, [old_key], allow_old=True)
        self.assertTrue((self.root/'installs'/self.old['generation']).exists())
        # Cache cleanup stays available while the game runs.
        result = storage.cleanup(self.engine, [self.cache_key])
        self.assertEqual(result.removed, 1)

    def test_revalidates_state_before_any_deletion(self):
        self.inventory()
        self.write_state(self.old,self.active)
        with self.assertRaisesRegex(UpdaterError,'保护'):
            storage.cleanup(self.engine,[self.cache_key,'installs/'+self.old['generation']],allow_old=True)
        self.assertTrue((self.root/'cache'/f"{self.cache_key.split('/')[1]}.part").exists())
        self.assertTrue((self.root/'installs'/self.old['generation']).exists())

    def test_unknown_and_outside_keys_are_rejected(self):
        for key in ('cache/unrelated.txt','installs/../../outside','installs/'+self.active['generation']):
            with self.subTest(key=key), self.assertRaises(UpdaterError):
                storage.cleanup(self.engine,[key],allow_old=True)
        self.assertTrue((self.root/'cache/unrelated.txt').exists())

    @unittest.skipIf(os.name=='nt','Symlink creation requires Windows developer privileges')
    def test_links_are_not_traversed_or_offered_for_cleanup(self):
        outside = self.base/'outside'
        outside.mkdir()
        (outside/'keep').write_text('keep')
        (self.root/'cache/external').symlink_to(outside,target_is_directory=True)
        inventory=self.inventory()
        linked=next(item for item in inventory.items if item.name=='external')
        self.assertFalse(linked.deletable)
        with self.assertRaises(UpdaterError):
            storage.cleanup(self.engine,[linked.key])
        old_path=self.root/'installs'/self.old['generation']
        (old_path/'game/saves').symlink_to(outside,target_is_directory=True)
        storage.cleanup(self.engine,['installs/'+self.old['generation']],allow_old=True)
        self.assertEqual((outside/'keep').read_text(),'keep')

    @unittest.skipIf(os.name=='nt','Symlink creation requires Windows developer privileges')
    def test_managed_container_link_is_refused(self):
        shutil.rmtree(self.root/'cache')
        outside=self.base/'outside-cache'
        outside.mkdir()
        (outside/'keep').write_text('keep')
        (self.root/'cache').symlink_to(outside,target_is_directory=True)
        inventory=self.inventory()
        self.assertTrue(inventory.warnings)
        self.assertFalse(any(item.kind=='cache' for item in inventory.items))
        with self.assertRaises(UpdaterError):
            storage.cleanup(self.engine,[self.cache_key])
        self.assertTrue((outside/'keep').exists())

    def test_corrupt_receipt_is_view_only(self):
        receipt=self.root/'installs'/self.old['generation']/'receipt.json'
        receipt.write_text('broken-json')
        item=next(item for item in self.inventory().items if item.path==receipt.parent)
        self.assertFalse(item.deletable)
        self.assertEqual(item.kind,'other')

    def test_cancel_scan_and_entry_limit_leave_files_unchanged(self):
        cancel=threading.Event(); cancel.set()
        with self.assertRaises(Cancelled):
            storage.scan(self.engine,cancel)
        with patch('rf_updater.storage.MAX_SCAN_ENTRIES',1):
            with self.assertRaisesRegex(UpdaterError,'限制|超过'):
                self.inventory()
        with patch('rf_updater.storage.MAX_LIST_ITEMS',1):
            with self.assertRaisesRegex(UpdaterError,'项目过多'):
                self.inventory()
        self.assertTrue((self.root/'cache/unrelated.txt').exists())

    def test_cleanup_lock_and_partial_permission_failure(self):
        with exclusive(self.root), self.assertRaisesRegex(UpdaterError,'另一个更新器'):
            storage.cleanup(self.engine,[self.cache_key])
        with patch('rf_updater.storage.shutil.rmtree',side_effect=PermissionError('fixture denied')):
            result=storage.cleanup(self.engine,[self.cache_key,'installs/'+self.old['generation']],allow_old=True)
        self.assertEqual(result.removed,1)
        self.assertEqual(len(result.errors),1)
        self.assertTrue((self.root/'installs'/self.old['generation']).exists())

    def test_directory_switch_remembers_choice_without_moving_any_data(self):
        destination=self.base/'new-location'
        destination.mkdir()
        marker=destination/'unrelated.txt'; marker.write_text('unchanged')
        original=(self.root/'state.json').read_bytes()
        candidate=storage.switch_directory(self.engine,destination)
        self.assertEqual(candidate.root,destination.resolve())
        self.assertIsNone(candidate.state()['active'])
        self.assertEqual((self.root/'state.json').read_bytes(),original)
        self.assertTrue((self.root/'installs'/self.active['generation']).exists())
        self.assertEqual(marker.read_text(),'unchanged')
        self.assertFalse((self.root/'.updater.lock').exists())
        remembered=Engine(target='linux')
        self.assertEqual(remembered.root,destination.resolve())
        self.assertTrue(remembered.root_must_exist)
        self.assertIn(self.root,preferences.choices(destination))
        self.assertEqual(Engine(self.root,'linux').root,self.root)

    def test_missing_saved_directory_does_not_get_recreated(self):
        destination=self.base/'external-disk'
        destination.mkdir()
        storage.switch_directory(self.engine,destination)
        remembered=Engine(target='linux')
        shutil.rmtree(destination)
        for action in (remembered.state,remembered.rollback,lambda: remembered.verify(threading.Event()),
                       lambda: remembered.install(Release('linux','https://example.com/a'),threading.Event())):
            with self.assertRaisesRegex(UpdaterError,'目录暂不可用'):
                action()
            self.assertFalse(destination.exists())

    def test_directory_switch_failures_preserve_preferences_and_current_data(self):
        destination=self.base/'new-location'; destination.mkdir()
        preferences.remember_root(self.root,self.root)
        before=self.config.read_bytes()
        for invalid in (self.root/'nested',self.root.parent,self.base/'absent'):
            with self.assertRaises(UpdaterError):
                storage.switch_directory(self.engine,invalid)
        with patch('rf_updater.storage.tempfile.TemporaryFile',side_effect=PermissionError('read only')):
            with self.assertRaises(PermissionError):
                storage.switch_directory(self.engine,destination)
        atomic_json(destination/'state.json',{'schema':999})
        with self.assertRaises(UpdaterError):
            storage.switch_directory(self.engine,destination)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(self.engine.state()['active'],self.active)

    def test_corrupt_preferences_can_be_repaired_from_explicit_root(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('not json')
        with self.assertRaises(UpdaterError):
            Engine(target='linux')
        explicit=Engine(self.root,'linux')
        self.assertEqual(explicit.root,self.root)
        destination=self.base/'new-location';destination.mkdir()
        storage.switch_directory(explicit,destination)
        self.assertEqual(preferences.saved_root(),destination.resolve())

    def test_target_state_fields_are_validated_before_remembering_directory(self):
        destination=self.base/'invalid-record'
        destination.mkdir()
        preferences.remember_root(self.root,self.root)
        before=self.config.read_bytes()
        bad={**self.active, 'installed_at':None}
        atomic_json(destination/'state.json',{'schema':1,'active':bad,'previous':None})
        with self.assertRaisesRegex(UpdaterError,'记录不完整'):
            storage.switch_directory(self.engine,destination)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(self.engine.state()['active'],self.active)


if __name__=='__main__':
    unittest.main()
