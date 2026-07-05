from rest_framework import serializers
from django.contrib.auth.models import User, Group
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


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

        user = self.user
        grupos = list(user.groups.values_list("name", flat=True))

        data["user"] = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "roles": grupos,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        }

        return data


class UserMeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    roles = serializers.ListField()
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()

class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = [
            "id",
            "name",
        ]


class AdminUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True
    )
    groups = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.all(),
        many=True,
        required=False
    )
    group_names = serializers.SerializerMethodField()

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
            "date_joined",
            "last_login",
        ]
        read_only_fields = [
            "id",
            "is_superuser",
            "date_joined",
            "last_login",
            "group_names",
        ]

    def get_group_names(self, obj):
        return list(obj.groups.values_list("name", flat=True))

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        groups = validated_data.pop("groups", [])

        user = User(**validated_data)
        user.is_staff = True

        if password:
            user.set_password(password)
        else:
            raise serializers.ValidationError({
                "password": "La contraseña es obligatoria para crear un usuario."
            })

        user.save()
        user.groups.set(groups)

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        groups = validated_data.pop("groups", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if groups is not None:
            instance.groups.set(groups)

        return instance


class ChangePasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError(
                "La contraseña debe tener al menos 8 caracteres."
            )
        return value