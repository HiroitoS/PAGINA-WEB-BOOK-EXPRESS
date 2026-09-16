from django.contrib.auth.models import Group, User
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .permission_registry import (
    FUNCTIONAL_PERMISSION_CODES,
    get_functional_permissions_queryset,
    get_permission_metadata,
    permission_code,
)


def get_user_permissions(user):
    if not user or not user.is_authenticated:
        return []

    return sorted(user.get_all_permissions())


def get_user_auth_data(user):
    roles = list(
        user.groups.values_list("name", flat=True).order_by("name")
    )

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "roles": roles,
        "permissions": get_user_permissions(user),
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }


def get_group_functional_permission_codes(group):
    codes = []

    for permission in (
        group.permissions
        .select_related("content_type")
        .all()
    ):
        code = permission_code(permission)

        if code in FUNCTIONAL_PERMISSION_CODES:
            codes.append(code)

    return sorted(codes)


def get_user_direct_permission_codes(user):
    codes = []

    for permission in (
        user.user_permissions
        .select_related("content_type")
        .all()
    ):
        code = permission_code(permission)

        if code in FUNCTIONAL_PERMISSION_CODES:
            codes.append(code)

    return sorted(codes)


def get_user_inherited_permission_codes(user):
    codes = set()

    groups = (
        user.groups
        .prefetch_related("permissions__content_type")
        .all()
    )

    for group in groups:
        for permission in group.permissions.all():
            code = permission_code(permission)

            if code in FUNCTIONAL_PERMISSION_CODES:
                codes.add(code)

    return sorted(codes)


def get_user_effective_functional_permission_codes(user):
    if user.is_superuser:
        return sorted(FUNCTIONAL_PERMISSION_CODES)

    return sorted(
        set(get_user_direct_permission_codes(user))
        | set(get_user_inherited_permission_codes(user))
    )


class LoginSerializer(TokenObtainPairSerializer):
    """
    Login JWT personalizado para Book Express.
    Devuelve tokens y datos del usuario.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        grupos = list(user.groups.values_list("name", flat=True))

        token["username"] = user.username
        token["email"] = user.email
        token["roles"] = grupos
        token["is_staff"] = user.is_staff
        token["is_superuser"] = user.is_superuser

        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = get_user_auth_data(self.user)

        return data


class UserMeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    roles = serializers.ListField()
    permissions = serializers.ListField()
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()


class GroupSerializer(serializers.ModelSerializer):
    functional_permissions = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "name",
            "functional_permissions",
        ]

    def get_functional_permissions(self, obj):
        return get_group_functional_permission_codes(obj)


class AdminUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )
    groups = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.all(),
        many=True,
        required=False,
    )
    group_names = serializers.SerializerMethodField()
    functional_permission_ids = serializers.PrimaryKeyRelatedField(
        queryset=get_functional_permissions_queryset(),
        many=True,
        required=False,
        write_only=True,
    )
    direct_permission_ids = serializers.SerializerMethodField()
    direct_permission_codes = serializers.SerializerMethodField()
    inherited_permission_codes = serializers.SerializerMethodField()
    effective_functional_permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "group_names",
            "functional_permission_ids",
            "direct_permission_ids",
            "direct_permission_codes",
            "inherited_permission_codes",
            "effective_functional_permissions",
            "date_joined",
            "last_login",
        ]
        read_only_fields = [
            "id",
            "is_superuser",
            "date_joined",
            "last_login",
            "group_names",
            "direct_permission_ids",
            "direct_permission_codes",
            "inherited_permission_codes",
            "effective_functional_permissions",
        ]

    def get_group_names(self, obj):
        return list(
            obj.groups
            .values_list("name", flat=True)
            .order_by("name")
        )

    def get_direct_permission_ids(self, obj):
        functional_ids = set(
            get_functional_permissions_queryset()
            .values_list("id", flat=True)
        )

        return sorted(
            permission_id
            for permission_id in obj.user_permissions.values_list(
                "id",
                flat=True,
            )
            if permission_id in functional_ids
        )

    def get_direct_permission_codes(self, obj):
        return get_user_direct_permission_codes(obj)

    def get_inherited_permission_codes(self, obj):
        return get_user_inherited_permission_codes(obj)

    def get_effective_functional_permissions(self, obj):
        return get_user_effective_functional_permission_codes(obj)

    def validate(self, attrs):
        instance = getattr(self, "instance", None)

        if "groups" in attrs:
            groups = list(attrs["groups"])
        elif instance is not None:
            groups = list(instance.groups.all())
        else:
            groups = []

        if "functional_permission_ids" in attrs:
            direct_permissions = list(
                attrs["functional_permission_ids"]
            )
        elif instance is not None:
            direct_permissions = list(instance.user_permissions.all())
        else:
            direct_permissions = []

        available_codes = set()

        for group in groups:
            available_codes.update(
                get_group_functional_permission_codes(group)
            )

        direct_codes = {
            permission_code(permission)
            for permission in direct_permissions
        }
        available_codes.update(direct_codes)

        missing_requirements = []

        for code in sorted(direct_codes):
            metadata = get_permission_metadata(code)

            if not metadata:
                continue

            for required_code in metadata["requires"]:
                if required_code not in available_codes:
                    missing_requirements.append(
                        f"{code} requiere {required_code}"
                    )

        if missing_requirements:
            raise serializers.ValidationError({
                "functional_permission_ids": [
                    "No se puede guardar esta combinación de permisos.",
                    *missing_requirements,
                ]
            })

        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        groups = validated_data.pop("groups", [])
        functional_permissions = validated_data.pop(
            "functional_permission_ids",
            [],
        )

        user = User(**validated_data)
        user.is_staff = True

        if password:
            user.set_password(password)
        else:
            raise serializers.ValidationError({
                "password": (
                    "La contraseña es obligatoria para crear "
                    "un usuario."
                )
            })

        user.save()
        user.groups.set(groups)
        self._set_functional_permissions(
            user,
            functional_permissions,
        )

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        groups = validated_data.pop("groups", None)
        functional_permissions = validated_data.pop(
            "functional_permission_ids",
            None,
        )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if groups is not None:
            instance.groups.set(groups)

        if functional_permissions is not None:
            self._set_functional_permissions(
                instance,
                functional_permissions,
            )

        return instance

    def _set_functional_permissions(self, user, permissions):
        """
        Reemplaza únicamente los permisos funcionales administrados por
        Book Express y conserva permisos directos ajenos a esta matriz.
        """
        managed_ids = set(
            get_functional_permissions_queryset()
            .values_list("id", flat=True)
        )

        preserved_permissions = list(
            user.user_permissions
            .exclude(id__in=managed_ids)
        )

        user.user_permissions.set([
            *preserved_permissions,
            *permissions,
        ])


class ChangePasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError(
                "La contraseña debe tener al menos 8 caracteres."
            )

        return value
