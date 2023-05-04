# Disables for testing:
# pylint: disable=missing-docstring
# pylint: disable=protected-access
# pylint: disable=too-many-public-methods
# pylint: disable=no-member
from uuid import uuid4
from django import forms
from django.contrib.auth.models import User
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django_gcp.exceptions import MissingBlobError

from tests.server.example.models import ExampleBlankBlobFieldModel, ExampleBlobFieldModel
from ._utils import get_admin_add_view_url, get_admin_change_view_url
from .test_storage_operations import StorageOperationsMixin


class BlobForm(forms.ModelForm):
    """Dummy form for testing modeladmin"""

    class Meta:
        model = ExampleBlobFieldModel
        fields = ["blob"]


class BlankBlobForm(forms.ModelForm):
    """Dummy form for testing modeladmin"""

    class Meta:
        model = ExampleBlankBlobFieldModel
        fields = ["blob"]


class BlobModelFactoryMixin:
    def _create(self, Model, name=None, content="", **create_kwargs):
        """Through the ORM, we may need to create blobs directly at the destination"""
        with override_settings(GCP_STORAGE_ALLOW_PATH_OVERRIDE=True):
            if name is not None:
                blob_name = self._prefix_blob_name(name)
                self._create_test_blob(self.bucket, blob_name, content)
                blob = {"path": blob_name}
            else:
                blob = None
            obj = Model.objects.create(blob=blob, **create_kwargs)
            obj.save()
        return obj


class TestBlobFieldAdmin(StorageOperationsMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole test case (used within the outer transaction to increase speed)"""
        User.objects.create_superuser(username="superuser", password="secret", email="admin@example.com")

    def setUp(self, *args, **kwargs):
        """Log in the superuser"""
        super().setUp(*args, **kwargs)
        self.client = Client()
        self.client.login(username="superuser", password="secret")

    def test_add_view_loads_normally(self):
        response = self.client.get(get_admin_add_view_url(ExampleBlobFieldModel))
        self.assertEqual(response.status_code, 200)

    def test_add_view_has_presigned_url(self):
        """The add view must have a presigned URL available in the context for uploading to a temporary path"""
        response = self.client.get(get_admin_add_view_url(ExampleBlobFieldModel))
        self.assertEqual(response.status_code, 200)
        widget = response.context_data["adminform"].fields["blob"].widget
        self.assertTrue(hasattr(widget, "signed_ingress_url"))
        self.assertTrue(
            widget.signed_ingress_url.startswith("https://storage.googleapis.com/example-media-assets/_tmp")
        )

    @override_settings(GCP_STORAGE_OVERRIDE_BLOBFIELD_VALUE=True)
    def test_change_view_loads_normally(self):
        """Ensure we can load a change view"""

        blob_name = self._prefix_blob_name("test_change_view_loads_normally.txt")
        self._create_test_blob(self.bucket, blob_name, "")
        obj = ExampleBlobFieldModel.objects.create(blob={"path": blob_name})

        # Assert that the view loads
        response = self.client.get(get_admin_change_view_url(obj))
        self.assertEqual(response.status_code, 200)

        # Assert the widget contents
        widget = response.context_data["adminform"].fields["blob"].widget
        self.assertTrue(hasattr(widget, "signed_ingress_url"))
        self.assertTrue(
            widget.signed_ingress_url.startswith("https://storage.googleapis.com/example-media-assets/_tmp")
        )


class TestBlobField(StorageOperationsMixin, TransactionTestCase):
    """Inherits from transaction test case, because we use an on_commit
    hook to move ingressed files once a database save has been made

    TODO REMOVE TRANSACTION TEST CASE
    as per https://code.djangoproject.com/ticket/30457
    ```
    with self.captureOnCommitCallbacks(execute=True) as callbacks:
        with transaction.atomic():
            transaction.on_commit(branch_1)
    ```
    """

    def test_validates_blob_exists_on_add(self):
        """Ensure that a ValidationError is raised if the blob at _tmp_path does not exist"""

        form = BlobForm(data={"blob": {"name": "thing", "_tmp_path": "something"}})
        form.is_valid()
        self.assertEqual(
            form.errors["blob"],
            ["Upload incomplete or failed (no blob at 'something' in bucket 'example-media-assets')"],
        )

    def test_validates_name_is_present_on_add(self):
        """Ensure that a ValidationError is raised if no 'name' property is present in the blob data"""

        form = BlobForm(data={"blob": {"_tmp_path": "something"}})

        self.assertEqual(
            form.errors["blob"],
            [
                "Both `_tmp_path` and `name` properties must be present in data for ExampleBlobFieldModel.blob if ingressing a new blob."
            ],
        )

    def test_validates_path_not_present_on_add(self):
        """Ensure that a ValidationError is raised if no 'name' property is present in the blob data"""

        form = BlobForm(data={"blob": {"name": "something", "_tmp_path": "something", "path": "something"}})

        self.assertEqual(
            form.errors["blob"],
            ["You cannot specify a path directly"],
        )

    def test_validates_tmp_path_is_present_on_add(self):
        """Ensure that a ValidationError is raised if no 'name' property is present in the blob data"""

        form = BlobForm(data={"blob": {"name": "something"}})

        self.assertEqual(
            form.errors["blob"],
            [
                "Both `_tmp_path` and `name` properties must be present in data for ExampleBlobFieldModel.blob if ingressing a new blob."
            ],
        )

    def test_validates_raises_on_add_blank_dict(self):
        form = BlobForm(data={"blob": {}})
        self.assertEqual(
            form.errors["blob"],
            ["This field is required."],
        )

    def test_validates_raises_on_add_blank_string(self):
        form = BlobForm(data={"blob": ""})

        self.assertEqual(
            form.errors["blob"],
            ["This field is required."],
        )

    def test_validates_raises_on_add_blank_none(self):
        form = BlobForm(data={"blob": None})

        self.assertEqual(
            form.errors["blob"],
            ["This field is required."],
        )

    def test_create_object_fails_with_missing_blob(self):
        """Create an object but fail to copy the blob (because it's missing) then check that
        no database record was created"""
        with self.assertRaises(MissingBlobError):
            obj = ExampleBlobFieldModel.objects.create(
                blob={"_tmp_path": f"_tmp/{uuid4()}.txt", "name": "missing_blob.txt"}
            )
            obj.save()
        count = ExampleBlobFieldModel.objects.count()
        self.assertEqual(count, 0)

    @override_settings(GCP_STORAGE_OVERRIDE_BLOBFIELD_VALUE=True)
    def test_create_object_succeeds_with_overridden_path(self):
        """Through the ORM, we may need to create blobs directly at the destination"""

        blob_name = self._prefix_blob_name("create_object_succeeds_with_overridden_path.txt")
        self._create_test_blob(self.bucket, blob_name, "")
        obj = ExampleBlobFieldModel.objects.create(blob={"path": blob_name})
        obj.save()
        count = ExampleBlobFieldModel.objects.count()
        self.assertEqual(count, 1)


class TestBlankBlobField(BlobModelFactoryMixin, StorageOperationsMixin, TransactionTestCase):
    """Inherits from transaction test case, because we use an on_commit
    hook to move ingressed files once a database save has been made

    TODO REMOVE TRANSACTION TEST CASE
    as per https://code.djangoproject.com/ticket/30457
    ```
    with self.captureOnCommitCallbacks(execute=True) as callbacks:
        with transaction.atomic():
            transaction.on_commit(branch_1)
    ```
    """

    def test_validates_on_add_blank_dict(self):
        form = BlankBlobForm(data={"blob": {}})
        self.assertNotIn("blob", form.errors)

    def test_validates_on_add_blank_string(self):
        form = BlankBlobForm(data={"blob": ""})
        self.assertNotIn("blob", form.errors)

    def test_validates_on_add_blank_none(self):
        form = BlankBlobForm(data={"blob": None})
        self.assertNotIn("blob", form.errors)

    def test_update_valid_to_blank(self):

        # Create a valid instance
        name = self._prefix_blob_name("update_valid_to_blank.txt")
        tmp_blob = self._create_temporary_blob(self.bucket)
        form = BlankBlobForm(data={"blob": {"_tmp_path": tmp_blob.name, "name": name}})
        instance = form.save()

        # Create a form to change this instance and set the data blank
        form = BlankBlobForm(instance=instance, data={"blob": {}})
        self.assertTrue(form.is_valid())
        form.save()
        instance.refresh_from_db()
        self.assertIsNone(instance.blob)

    def test_update_blank_to_valid(self):

        # Create a blank instance
        form = BlankBlobForm(data={"blob": {}})
        instance = form.save()
        instance.refresh_from_db()

        name = self._prefix_blob_name("update_blank_to_valid.txt")
        tmp_blob = self._create_temporary_blob(self.bucket)

        # Create a form to change this instance and set the data to a real value
        form = BlankBlobForm(instance=instance, data={"blob": {"_tmp_path": tmp_blob.name, "name": name}})
        self.assertTrue(form.is_valid())
        form.save()
        instance.refresh_from_db()
        self.assertIsNotNone(instance.blob)
        self.assertIn("path", instance.blob)
        self.assertEqual(instance.blob["path"], name)

    def test_update_valid_to_valid(self):

        # Create a valid instance
        name = self._prefix_blob_name("update_valid_to_valid.txt")
        tmp_blob = self._create_temporary_blob(self.bucket)
        form = BlankBlobForm(data={"blob": {"_tmp_path": tmp_blob.name, "name": name}})
        instance = form.save()
        instance.refresh_from_db()

        new_name = self._prefix_blob_name("overwrite_update_valid_to_valid.txt")
        tmp_blob = self._create_temporary_blob(self.bucket)

        # Create a form to change this instance and set the data to a real value
        form = BlankBlobForm(instance=instance, data={"blob": {"_tmp_path": tmp_blob.name, "name": new_name}})
        self.assertTrue(form.is_valid())
        form.save()
        instance.refresh_from_db()
        self.assertIsNotNone(instance.blob)
        self.assertIn("path", instance.blob)
        self.assertEqual(instance.blob["path"], new_name)

    def test_update_valid_unchanged(self):

        # Create a valid instance
        name = self._prefix_blob_name("update_valid_unchanged.txt")
        tmp_blob = self._create_temporary_blob(self.bucket)
        form = BlankBlobForm(data={"blob": {"_tmp_path": tmp_blob.name, "name": name}})
        instance = form.save()
        instance.refresh_from_db()
        self.assertIsNotNone(instance.blob)
        self.assertIn("path", instance.blob)
        self.assertEqual(instance.blob["path"], name)

        # Create a form to update the instance but leave the blobfield unchanged
        form = BlankBlobForm(instance=instance, data={"blob": {"path": name}, "category": "test"})
        self.assertTrue(form.is_valid())
        form.save()