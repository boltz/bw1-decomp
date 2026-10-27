#include "LH3DMeshIntersect.h"
#include "LH3DMesh.h"
#include "LH3DSubMesh.h"
#include "LH3DPrimitive.h"
#include "LH3DVertexGroup.h"
#include "LH3DTexture.h"
#include "LH3DColor.h"
#include "LHPoint.h"
#include "LHMatrix.h"
#include "LH3DMath.h"
#include <Lionhead/LHFile/ver3.0/LHFile.h>
#include <stdio.h>
#include <math.h>

namespace
{
LH3DColor         OldCols[SCAR_TEXTURE_SIZE][SCAR_TEXTURE_SIZE];
LH3DColor         NewCols[SCAR_TEXTURE_SIZE][SCAR_TEXTURE_SIZE];
long              GpIdx[MESH_INTERSECT_MAX_VERTICES];
uint32_t          WorldTris[MESH_INTERSECT_MAX_VERTICES][MESH_INTERSECT_TRIANGLE_VERTICES];
LHPoint           WorldPoints[MESH_INTERSECT_MAX_VERTICES];
LHPoint           WorldHitPos;
MeshIntersectData GMeshIntersect;
bool              ScarLoaded;
// clang-format off
}
// clang-format on

// BW1W120 00866ec0 BW1M119 0106e560 (LHCombined Release)
void LoadScar();

void MeshIntersect::InitialiseMeshIntersect()
{
	GMeshIntersect.WorldPoints = WorldPoints;
	GMeshIntersect.WorldTris = WorldTris;
	GMeshIntersect.TriangleCount = 0;
}

void TextureRef::ColourIntersectionPoint(LH3DMesh* mesh, LH3DColor* colour, float blend)
{
	int skinIndex = Skin;
	if (skinIndex >= mesh->SkinCount)
	{
		skinIndex = 0;
	}

	LH3DTexture* texture = reinterpret_cast<LH3DTexture**>(mesh->skins)[skinIndex];
	LH3DSurfDesc surface;
	texture->Lock(&surface);

	if (surface.Surface != NULL && (surface.Width == SCAR_TEXTURE_SIZE || surface.Width == SCAR_SMALL_TEXTURE_SIZE))
	{
		unsigned int column = U;
		unsigned int row = V;
		if (surface.Width == SCAR_SMALL_TEXTURE_SIZE)
		{
			column >>= 1;
			row >>= 1;
		}

		uint16_t*     pixel = static_cast<uint16_t*>(surface.Surface) + row * surface.Width + column;
		unsigned long oldPixel = *pixel;
		float         oldWeight = 1.0f - blend;

		long red = static_cast<long>(((oldPixel >> 4) & 0xf0) * oldWeight + colour->r * blend);
		long blue = static_cast<long>(((oldPixel & 0xf) << 4) * oldWeight + colour->b * blend);
		long green = static_cast<long>((oldPixel & 0xf0) * oldWeight + colour->g * blend);

		*pixel = 0xf000 | ((red & 0xf0) << 4) | ((blue >> 4) & 0xf) | (green & 0xf0);

		uint32_t textureType = texture->GetType();
		if (textureType == LH3D_TEXTURE_TYPE_NAMED || textureType == LH3D_TEXTURE_TYPE_SYSTEM_MEMORY)
		{
			texture->ReloadPending = true;
		}
	}

	texture->Unlock();
}

void MeshIntersect::WriteBinary(LHFile* file)
{
	uint32_t index = PrimitiveIndex;
	file->WriteSegmentData(&index, sizeof(index));

	for (int vertex = 0; vertex < MESH_INTERSECT_TRIANGLE_VERTICES; ++vertex)
	{
		index = VertexIndices[vertex];
		file->WriteSegmentData(&index, sizeof(index));
	}

	for (int group = 0; group < MESH_INTERSECT_TRIANGLE_VERTICES; ++group)
	{
		index = VertexGroupIndices[group];
		file->WriteSegmentData(&index, sizeof(index));
	}

	float weight = Beta;
	file->WriteSegmentData(&weight, sizeof(weight));
	weight = Gamma;
	file->WriteSegmentData(&weight, sizeof(weight));
}

void MeshIntersect::ReadBinary(LHFile* file)
{
	uint32_t index;
	file->GetSegmentData(&index, sizeof(index), LH_FILE_CURRENT_POSITION);
	PrimitiveIndex = index;
	for (int vertex = 0; vertex < MESH_INTERSECT_TRIANGLE_VERTICES; ++vertex)
	{
		file->GetSegmentData(&index, sizeof(index), LH_FILE_CURRENT_POSITION);
		VertexIndices[vertex] = index;
	}
	for (int group = 0; group < MESH_INTERSECT_TRIANGLE_VERTICES; ++group)
	{
		file->GetSegmentData(&index, sizeof(index), LH_FILE_CURRENT_POSITION);
		VertexGroupIndices[group] = index;
	}
	float weight;
	file->GetSegmentData(&weight, sizeof(weight), LH_FILE_CURRENT_POSITION);
	Beta = weight;
	file->GetSegmentData(&weight, sizeof(weight), LH_FILE_CURRENT_POSITION);
	Gamma = weight;
	SubmeshIndex = 0;
}

void MeshIntersect::ObtainPointColour(LH3DMesh* mesh, unsigned long* colour)
{
	LH3DPrimitive* primitive = mesh->submeshes[0]->primitives_[PrimitiveIndex];
	LH3DTexture*   texture = primitive->Material.texture;
	LH3DSurfDesc   surface;
	texture->Lock(&surface);

	if (surface.Surface != NULL && (surface.Width == SCAR_TEXTURE_SIZE || surface.Width == SCAR_SMALL_TEXTURE_SIZE))
	{
		const LHCoordF& firstUV = primitive->Vertices[VertexIndices[0]].uv;
		const LHCoordF& secondUV = primitive->Vertices[VertexIndices[1]].uv;
		const LHCoordF& thirdUV = primitive->Vertices[VertexIndices[2]].uv;
		float           textureSize = surface.Width;

		unsigned long textureU = static_cast<long>(
			((thirdUV.X() - firstUV.X()) * Gamma + (secondUV.X() - firstUV.X()) * Beta + firstUV.X()) * textureSize);
		unsigned long textureV = static_cast<long>(
			((thirdUV.Y() - firstUV.Y()) * Gamma + (secondUV.Y() - firstUV.Y()) * Beta + firstUV.Y()) * textureSize);

		textureU = min(textureU, surface.Width - 1);
		textureV = min(textureV, surface.Width - 1);

		textureU &= LH3D_COLOR_CHANNEL_MASK;
		textureV &= LH3D_COLOR_CHANNEL_MASK;

		uint16_t*     pixels = static_cast<uint16_t*>(surface.Surface);
		unsigned long texel = pixels[textureV * surface.Width + textureU];
		LH3DColor     sampledColour((texel >> 4) & 0xf0, texel & 0xf0, (texel & 0xf) << 4, LH3D_COLOR_OPAQUE);
		*colour = sampledColour.GetColor();
	}

	texture->Unlock();
}

void LoadScar()
{
	ScarLoaded = true;

	FILE* rgbFile = fopen("data\\damage_new256.raw", "rb");
	if (rgbFile == NULL)
	{
		return;
	}

	FILE* alphaFile = fopen("data\\damage_new256A.raw", "rb");
	if (alphaFile == NULL)
	{
		fclose(rgbFile);
		return;
	}

	for (int row = 0; row < SCAR_TEXTURE_SIZE; ++row)
	{
		for (int column = 0; column < SCAR_TEXTURE_SIZE; ++column)
		{
			uint8_t red = fgetc(rgbFile);
			uint8_t green = fgetc(rgbFile);
			uint8_t blue = fgetc(rgbFile);
			uint8_t alpha = fgetc(alphaFile);
			NewCols[row][column].Set(alpha, red, green, blue);
		}
	}

	fclose(rgbFile);
	fclose(alphaFile);

	rgbFile = fopen("data\\damage_old256.raw", "rb");
	if (rgbFile == NULL)
	{
		return;
	}

	alphaFile = fopen("data\\damage_old256A.raw", "rb");
	if (alphaFile == NULL)
	{
		fclose(rgbFile);
		return;
	}

	for (int oldRow = 0; oldRow < SCAR_TEXTURE_SIZE; ++oldRow)
	{
		for (int oldColumn = 0; oldColumn < SCAR_TEXTURE_SIZE; ++oldColumn)
		{
			uint8_t red = fgetc(rgbFile);
			uint8_t green = fgetc(rgbFile);
			uint8_t blue = fgetc(rgbFile);
			uint8_t alpha = fgetc(alphaFile);
			OldCols[oldRow][oldColumn].Set(alpha, red, green, blue);
		}
	}

	fclose(rgbFile);
	fclose(alphaFile);
}

bool32_t MeshIntersect::GetNearestIntersection(LH3DMesh* mesh, const LHMatrix* matrices, LHPoint* start,
                                               LHPoint* direction, bool collision_only, LHPoint* impact,
                                               LHPoint* inward_normal, bool both_directions)
{
	const int                 submeshCount = mesh->SubmeshCount;
	const LH3D_SUB_MESH_FLAGS requiredSubmeshFlag =
		collision_only ? LH3D_SUB_MESH_FLAGS_COLLISION : LH3D_SUB_MESH_FLAGS_INTERSECTION;
	bool32_t found = false;
	float    nearestParameter = 0.0f;

	for (int submeshIndex = 0; submeshIndex < submeshCount; ++submeshIndex)
	{
		LH3DSubMesh* submesh = mesh->submeshes[submeshIndex];
		if ((submesh->flags_ & requiredSubmeshFlag) == 0)
		{
			continue;
		}

		const int primitiveCount = submesh->NumPrimitives;
		for (int primitiveIndex = 0; primitiveIndex < primitiveCount; ++primitiveIndex)
		{
			LH3DPrimitive* primitive = submesh->primitives_[primitiveIndex];
			if ((mesh->flags & LH3D_MESH_FLAGS_HAS_BONES) == 0)
			{
				for (int vertexIndex = 0; vertexIndex < primitive->NumVertices; ++vertexIndex)
				{
					const LHPoint position = primitive->Vertices[vertexIndex].position;
					WorldPoints[vertexIndex] = matrices[0] * position;
					GpIdx[vertexIndex] = 0;
				}
			}
			else
			{
				int vertexIndex = 0;
				for (int groupIndex = 0; groupIndex < primitive->NumVertexGroups; ++groupIndex)
				{
					const LH3DVertexGroup& group = primitive->VertexGroups[groupIndex];
					const LHMatrix&        matrix = matrices[group.BoneIndex];
					for (int groupVertexIndex = 0; groupVertexIndex < group.vertex_count;
					     ++groupVertexIndex, ++vertexIndex)
					{
						const LHPoint position = primitive->Vertices[vertexIndex].position;
						WorldPoints[vertexIndex] = matrix * position;
						GpIdx[vertexIndex] = groupIndex;
					}
				}
			}

			for (int triangleIndex = 0; triangleIndex < primitive->NumTriangles; ++triangleIndex)
			{
				const LH3DTriangle& triangleIndices = primitive->Triangles[triangleIndex];
				const LHPoint       firstVertex = WorldPoints[triangleIndices.A];
				const LHPoint       secondVertex = WorldPoints[triangleIndices.B];
				const LHPoint       thirdVertex = WorldPoints[triangleIndices.C];
				const LHPoint       firstEdge = secondVertex - firstVertex;
				const LHPoint       secondEdge = thirdVertex - firstVertex;
				LHPoint             triangleNormal = firstEdge ^ secondEdge;

				triangleNormal.Normalise();

				const float directionProjection = (*direction) * triangleNormal;
				if (!(directionProjection < -MESH_INTERSECT_PARALLEL_EPSILON ||
				      MESH_INTERSECT_PARALLEL_EPSILON < directionProjection))
				{
					continue;
				}

				const float parameter =
					(firstVertex * triangleNormal - (*start) * triangleNormal) / directionProjection;
				if (!both_directions && !(0.0f < parameter))
				{
					continue;
				}

				const LHPoint candidate = (*direction) * parameter + (*start);
				int           positiveEdgeCount = 0;
				if (((firstEdge ^ (candidate - firstVertex)) * triangleNormal) > 0.0f)
				{
					++positiveEdgeCount;
				}
				if ((((thirdVertex - secondVertex) ^ (candidate - secondVertex)) * triangleNormal) > 0.0f)
				{
					++positiveEdgeCount;
				}
				if ((((firstVertex - thirdVertex) ^ (candidate - thirdVertex)) * triangleNormal) > 0.0f)
				{
					++positiveEdgeCount;
				}

				if (positiveEdgeCount != 0 && positiveEdgeCount != MESH_INTERSECT_TRIANGLE_VERTICES)
				{
					continue;
				}
				if (found && !(parameter < nearestParameter))
				{
					continue;
				}

				WorldHitPos = candidate;
				if (impact != NULL && inward_normal != NULL)
				{
					*impact = candidate;
					if (directionProjection <= 0.0f)
					{
						*inward_normal = LHPoint(-triangleNormal.x, -triangleNormal.y, -triangleNormal.z);
					}
					else
					{
						*inward_normal = triangleNormal;
					}
					found = true;
					nearestParameter = parameter;
					continue;
				}

				const float offsetX = candidate.x - firstVertex.x;
				const float offsetY = candidate.y - firstVertex.y;
				float       beta;
				float       gamma;
				if (fabs(secondEdge.x) <= MESH_INTERSECT_PARALLEL_EPSILON)
				{
					if (!(MESH_INTERSECT_PARALLEL_EPSILON < fabs(firstEdge.x)))
					{
						continue;
					}

					const float denominator = secondEdge.y - (firstEdge.y * secondEdge.x) / firstEdge.x;
					if (!(MESH_INTERSECT_PARALLEL_EPSILON < fabs(denominator)))
					{
						continue;
					}

					gamma = (offsetY - (offsetX * firstEdge.y) / firstEdge.x) / denominator;
					beta = (offsetX - gamma * secondEdge.x) / firstEdge.x;
				}
				else
				{
					const float denominator = firstEdge.y - (secondEdge.y * firstEdge.x) / secondEdge.x;
					if (!(MESH_INTERSECT_PARALLEL_EPSILON < fabs(denominator)))
					{
						continue;
					}

					beta = (offsetY - (offsetX * secondEdge.y) / secondEdge.x) / denominator;
					gamma = (offsetX - firstEdge.x * beta) / secondEdge.x;
				}

				if (!(0.0f <= beta && beta <= 1.0f && 0.0f <= gamma && gamma <= 1.0f))
				{
					continue;
				}

				found = true;
				VertexIndices[0] = triangleIndices.A;
				VertexIndices[1] = triangleIndices.B;
				VertexIndices[2] = triangleIndices.C;
				VertexGroupIndices[0] = GpIdx[VertexIndices[0]];
				VertexGroupIndices[1] = GpIdx[VertexIndices[1]];
				VertexGroupIndices[2] = GpIdx[VertexIndices[2]];
				Beta = beta;
				Gamma = gamma;
				PrimitiveIndex = primitiveIndex;
				SubmeshIndex = submeshIndex;
				nearestParameter = parameter;
			}
		}
	}

	return found;
}

void MeshIntersect::SetUpWorldPoints(LH3DMesh* mesh, const LHMatrix* matrices, MeshIntersectData* data)
{
	int worldVertexCount = 0;
	int worldTriangleCount = 0;

	for (int submeshIndex = 0; submeshIndex < mesh->SubmeshCount; ++submeshIndex)
	{
		LH3DSubMesh* submesh = mesh->submeshes[submeshIndex];
		for (int primitiveIndex = 0; primitiveIndex < submesh->NumPrimitives; ++primitiveIndex)
		{
			LH3DPrimitive* primitive = submesh->primitives_[primitiveIndex];
			int            firstWorldVertex = worldVertexCount;
			int            vertexIndex = 0;

			if (mesh->flags & LH3D_MESH_FLAGS_HAS_BONES)
			{
				for (int groupIndex = 0; groupIndex < primitive->NumVertexGroups; ++groupIndex)
				{
					const LH3DVertexGroup& group = primitive->VertexGroups[groupIndex];
					const LHMatrix&        matrix = matrices[group.BoneIndex];
					for (int groupVertex = 0; groupVertex < group.vertex_count; ++groupVertex)
					{
						data->WorldPoints[worldVertexCount] = matrix * primitive->Vertices[vertexIndex].position;
						GpIdx[vertexIndex] = groupIndex;
						++vertexIndex;
						++worldVertexCount;
					}
				}
			}
			else
			{
				for (; vertexIndex < primitive->NumVertices; ++vertexIndex)
				{
					data->WorldPoints[worldVertexCount] = matrices[0] * primitive->Vertices[vertexIndex].position;
					GpIdx[vertexIndex] = 0;
					++worldVertexCount;
				}
			}

			for (int triangleIndex = 0; triangleIndex < primitive->NumTriangles; ++triangleIndex)
			{
				const LH3DTriangle& triangle = primitive->Triangles[triangleIndex];
				data->WorldTris[worldTriangleCount][0] = firstWorldVertex + triangle.A;
				data->WorldTris[worldTriangleCount][1] = firstWorldVertex + triangle.B;
				data->WorldTris[worldTriangleCount][2] = firstWorldVertex + triangle.C;
				++worldTriangleCount;
			}
		}
	}

	data->TriangleCount = worldTriangleCount;
}

bool32_t MeshIntersect::GetImpactPointAlex(LHPoint& start, LHPoint& direction, LHPoint& impact, LHPoint& normal,
                                           MeshIntersectData* data, float limit)
{
	float    searchRadius = limit + MESH_INTERSECT_SEARCH_MARGIN;
	float    searchRadiusSquared = searchRadius * searchRadius;
	bool32_t found = false;
	float    nearestDistance;
	LHPoint  nearestImpact;
	LHPoint  nearestNormal;

	for (int triangleIndex = 0; triangleIndex < data->TriangleCount; ++triangleIndex)
	{
		const uint32_t* indices = data->WorldTris[triangleIndex];
		LHPoint         a = data->WorldPoints[indices[0]];
		LHPoint         b = data->WorldPoints[indices[1]];
		LHPoint         c = data->WorldPoints[indices[2]];

		if (!(a.GetDistanceSq(start) < searchRadiusSquared || b.GetDistanceSq(start) < searchRadiusSquared ||
		      c.GetDistanceSq(start) < searchRadiusSquared))
		{
			continue;
		}

		LHPoint edgeAB = b - a;
		LHPoint edgeAC = c - a;
		normal = edgeAB ^ edgeAC;
		if (!(normal * direction < MESH_INTERSECT_FACING_EPSILON))
		{
			continue;
		}

		normal *= InverseSquareRoot(normal * normal);
		float distance = (normal * a - normal * start) / (normal * direction);
		if (!(distance < limit && distance > 0.0f))
		{
			continue;
		}

		impact = start + direction * distance;
		int positiveSides = ((edgeAB ^ (impact - a)) * normal > 0.0f);
		positiveSides += (((c - b) ^ (impact - b)) * normal > 0.0f);
		positiveSides += (((impact - c) ^ edgeAC) * normal > 0.0f);
		if (positiveSides != 0 && positiveSides != MESH_INTERSECT_TRIANGLE_VERTICES)
		{
			continue;
		}

		if (!found || distance < nearestDistance)
		{
			nearestDistance = distance;
			nearestImpact = impact;
			nearestNormal = normal;
			found = true;
		}
	}

	if (!found)
	{
		return false;
	}

	normal = nearestNormal;
	impact = nearestImpact;
	return true;
}

bool32_t MeshIntersect::GetImpactPoint(LHPoint& start, LHPoint& direction, LHPoint& impact, LHPoint& normal,
                                       MeshIntersectData* data)
{
	for (int triangleIndex = 0; triangleIndex < data->TriangleCount; ++triangleIndex)
	{
		const uint32_t* indices = data->WorldTris[triangleIndex];
		LHPoint         a = data->WorldPoints[indices[0]];
		LHPoint         b = data->WorldPoints[indices[1]];
		LHPoint         c = data->WorldPoints[indices[2]];
		LHPoint         edgeAB = b - a;
		LHPoint         edgeAC = c - a;

		normal = edgeAB ^ edgeAC;
		if (!(normal * direction < MESH_INTERSECT_FACING_EPSILON))
		{
			continue;
		}

		normal *= InverseSquareRoot(normal * normal);
		float distance = (normal * a - normal * start) / (normal * direction);
		if (distance > 0.0f)
		{
			continue;
		}

		impact = start + direction * distance;
		if (!((edgeAB ^ (impact - a)) * normal > 0.0f))
		{
			continue;
		}
		if (!(((c - b) ^ (impact - b)) * normal > 0.0f))
		{
			continue;
		}
		if (!(((impact - c) ^ edgeAC) * normal > 0.0f))
		{
			continue;
		}

		return true;
	}

	return false;
}

bool32_t MeshIntersect::CreateFromTextureRef(LH3DMesh* mesh, LHMatrix* matrices, TextureRef* ref)
{
	LH3DTexture* texture = reinterpret_cast<LH3DTexture**>(mesh->skins)[ref->Skin];
	int          submeshCount = mesh->SubmeshCount;

	for (int submeshIndex = 0; submeshIndex < submeshCount; ++submeshIndex)
	{
		LH3DSubMesh* submesh = mesh->submeshes[submeshIndex];
		int          primitiveCount = submesh->NumPrimitives;

		for (int primitiveIndex = 0; primitiveIndex < primitiveCount; ++primitiveIndex)
		{
			LH3DPrimitive* primitive = submesh->primitives_[primitiveIndex];
			LH3DVertex*    vertices = primitive->Vertices;
			LH3DTexture*   primitiveTexture = primitive->Material.texture;
			primitiveTexture->format.GetWidth();

			int vertexIndex = 0;
			if (mesh->flags & LH3D_MESH_FLAGS_HAS_BONES)
			{
				for (int groupIndex = 0; groupIndex < primitive->NumVertexGroups; ++groupIndex)
				{
					LH3DVertexGroup* group = &primitive->VertexGroups[groupIndex];
					const LHMatrix&  matrix = matrices[group->BoneIndex];

					for (int groupVertex = 0; groupVertex < group->vertex_count; ++groupVertex)
					{
						WorldPoints[vertexIndex] = matrix * vertices[vertexIndex].position;
						GpIdx[vertexIndex] = groupIndex;
						++vertexIndex;
					}
				}
			}
			else
			{
				for (; vertexIndex < primitive->NumVertices; ++vertexIndex)
				{
					WorldPoints[vertexIndex] = matrices[0] * vertices[vertexIndex].position;
					GpIdx[vertexIndex] = 0;
				}
			}

			if (primitiveTexture != texture)
			{
				continue;
			}

			for (int triangleIndex = 0; triangleIndex < primitive->NumTriangles; ++triangleIndex)
			{
				const LH3DTriangle& triangle = primitive->Triangles[triangleIndex];
				VertexIndices[0] = triangle.A;
				VertexIndices[1] = triangle.B;
				VertexIndices[2] = triangle.C;

				const LHCoordF& firstUV = vertices[VertexIndices[0]].uv;
				const LHCoordF& secondUV = vertices[VertexIndices[1]].uv;
				const LHCoordF& thirdUV = vertices[VertexIndices[2]].uv;

				float secondDeltaU = secondUV.X() - firstUV.X();
				float secondDeltaV = secondUV.Y() - firstUV.Y();
				float thirdDeltaU = thirdUV.X() - firstUV.X();
				float thirdDeltaV = thirdUV.Y() - firstUV.Y();
				float determinant = thirdDeltaU * secondDeltaV - thirdDeltaV * secondDeltaU;

				if (fabs(determinant) > MESH_INTERSECT_UV_EPSILON)
				{
					float deltaU = ref->U * (1.0f / SCAR_TEXTURE_SIZE) - firstUV.X();
					float deltaV = ref->V * (1.0f / SCAR_TEXTURE_SIZE) - firstUV.Y();
					Gamma = (deltaU * secondDeltaV - deltaV * secondDeltaU) / determinant;
					Beta = (deltaV * thirdDeltaU - deltaU * thirdDeltaV) / determinant;

					if (Gamma >= 0.0f && Gamma <= 1.0f && Beta >= 0.0f && Beta <= 1.0f && Beta + Gamma <= 1.0f)
					{
						VertexGroupIndices[0] = GpIdx[VertexIndices[0]];
						VertexGroupIndices[1] = GpIdx[VertexIndices[1]];
						VertexGroupIndices[2] = GpIdx[VertexIndices[2]];
						PrimitiveIndex = primitiveIndex;
						SubmeshIndex = submeshIndex;
						return true;
					}
				}
			}
		}
	}

	return false;
}

void MeshIntersect::GetWorldPositionAndInwardNormal(LH3DMesh* mesh, const LHMatrix* matrices, LHPoint* position,
                                                    LHPoint* normal)
{
	LH3DPrimitive* primitive = mesh->submeshes[SubmeshIndex]->primitives_[PrimitiveIndex];
	LHPoint        worldVertices[MESH_INTERSECT_TRIANGLE_VERTICES];

	if (mesh->flags & LH3D_MESH_FLAGS_HAS_BONES)
	{
		for (int corner = 0; corner < MESH_INTERSECT_TRIANGLE_VERTICES; ++corner)
		{
			const LHMatrix& matrix = matrices[primitive->VertexGroups[VertexGroupIndices[corner]].BoneIndex];
			worldVertices[corner] = matrix * primitive->Vertices[VertexIndices[corner]].position;
		}
	}
	else
	{
		for (int corner = 0; corner < MESH_INTERSECT_TRIANGLE_VERTICES; ++corner)
		{
			worldVertices[corner] = matrices[0] * primitive->Vertices[VertexIndices[corner]].position;
		}
	}

	LHPoint secondEdge = worldVertices[1] - worldVertices[0];
	LHPoint thirdEdge = worldVertices[2] - worldVertices[0];
	normal->CrossProduct(thirdEdge, secondEdge);
	position->Set((worldVertices[0] + secondEdge * Beta) + thirdEdge * Gamma);
}

void MeshIntersect::GetWorldPositionInwardNormalAndAverageMatrix(LH3DMesh* mesh, const LHMatrix* matrices,
                                                                 LHPoint* position, LHPoint* normal, LHMatrix* average)
{
	LH3DPrimitive* primitive = mesh->submeshes[0]->primitives_[PrimitiveIndex];
	LH3DVertex*    vertices = primitive->Vertices;
	LHPoint        worldVertices[MESH_INTERSECT_TRIANGLE_VERTICES];

	for (int corner = 0; corner < MESH_INTERSECT_TRIANGLE_VERTICES; ++corner)
	{
		LHMatrix vertexMatrix = matrices[primitive->VertexGroups[VertexGroupIndices[corner]].BoneIndex];
		worldVertices[corner] = vertexMatrix * vertices[VertexIndices[corner]].position;
		vertexMatrix.NormaliseMatrixOnly();

		if (corner == 0)
		{
			average->Set(vertexMatrix);
		}
		else
		{
			average->GetVectorX() = vertexMatrix.GetVectorX() + average->GetVectorX();
			average->GetVectorY() = vertexMatrix.GetVectorY() + average->GetVectorY();
			average->GetVectorZ() = vertexMatrix.GetVectorZ() + average->GetVectorZ();
			average->GetPos() = vertexMatrix.GetPos() + average->GetPos();
		}
	}

	average->NormaliseMatrixOnly();
	average->SetTranslateOnly(LHPoint(0.0f, 0.0f, 0.0f));

	LHPoint secondEdge = worldVertices[1] - worldVertices[0];
	LHPoint thirdEdge = worldVertices[2] - worldVertices[0];
	normal->CrossProduct(thirdEdge, secondEdge);
	position->Set((worldVertices[0] + secondEdge * Beta) + thirdEdge * Gamma);
}
void MeshIntersect::GetTextureRef(LH3DMesh* mesh, TextureRef* ref)
{
	LH3DPrimitive* primitive = mesh->submeshes[0]->primitives_[PrimitiveIndex];
	long           skinIndex = 0;
	for (long index = 0; index < mesh->SkinCount; ++index)
	{
		if (reinterpret_cast<LH3DTexture**>(mesh->skins)[index] == primitive->Material.texture)
		{
			skinIndex = index;
		}
	}

	const LH3DVertex& first = primitive->Vertices[VertexIndices[0]];
	const LH3DVertex& second = primitive->Vertices[VertexIndices[1]];
	const LH3DVertex& third = primitive->Vertices[VertexIndices[2]];
	unsigned long     textureU = static_cast<long>(
		((second.uv.X() - first.uv.X()) * Beta + (third.uv.X() - first.uv.X()) * Gamma + first.uv.X()) *
		SCAR_TEXTURE_SIZE);
	unsigned long textureV = static_cast<long>(
		((second.uv.Y() - first.uv.Y()) * Beta + (third.uv.Y() - first.uv.Y()) * Gamma + first.uv.Y()) *
		SCAR_TEXTURE_SIZE);

	textureU = min(textureU, SCAR_TEXTURE_SIZE - 1);
	textureV = min(textureV, SCAR_TEXTURE_SIZE - 1);

	ref->U = textureU;
	ref->V = textureV;
	ref->Age = 0;
	ref->Skin = skinIndex;
}

void TextureRef::DrawCutAroundIntersectionPoint(LH3DMesh* mesh, float age)
{
	if (!ScarLoaded)
	{
		LoadScar();
	}

	int skinIndex = Skin;
	if (skinIndex >= mesh->SkinCount)
	{
		skinIndex = 0;
	}
	LH3DTexture* texture = reinterpret_cast<LH3DTexture**>(mesh->skins)[skinIndex];
	LH3DSurfDesc surface;
	texture->Lock(&surface);
	if (!surface.Surface || (surface.Width != SCAR_TEXTURE_SIZE && surface.Width != SCAR_SMALL_TEXTURE_SIZE))
	{
		texture->Unlock();
		return;
	}

	bool32_t      fullSize = surface.Width == SCAR_TEXTURE_SIZE;
	int           tileRow = Type * SCAR_TILE_SIZE;
	int           tileColumn = SubType * SCAR_TILE_SIZE;
	unsigned long blendAmount = static_cast<long>(age * LH3D_COLOR_OPAQUE);
	int           centerU = U;
	int           centerV = V;
	int           halfSize = SCAR_TILE_SIZE / 2;
	if (!fullSize)
	{
		centerU >>= 1;
		centerV >>= 1;
		halfSize >>= 1;
	}

	long      textureWidth = surface.Width;
	long      textureHeight = surface.Height;
	uint16_t* pixels = static_cast<uint16_t*>(surface.Surface);
	for (int row = 0; row < SCAR_TILE_SIZE; ++row)
	{
		if (!fullSize && !(row & 1))
		{
			continue;
		}
		int destinationV = centerV - halfSize + (fullSize ? row : row >> 1);

		for (int column = 0; column < SCAR_TILE_SIZE; ++column)
		{
			if (!fullSize && !(column & 1))
			{
				continue;
			}
			int destinationU = centerU - halfSize + (fullSize ? column : column >> 1);
			if (destinationU < 0 || destinationU >= textureWidth || destinationV < 0 || destinationV >= textureHeight)
			{
				continue;
			}

			const LH3DColor& oldColour = OldCols[tileRow + row][tileColumn + column];
			const LH3DColor& newColour = NewCols[tileRow + row][tileColumn + column];
			LH3DColor        blended;
			blended.r = newColour.r + (((oldColour.r - newColour.r) * blendAmount) >> 8);
			blended.g = newColour.g + (((oldColour.g - newColour.g) * blendAmount) >> 8);
			blended.b = newColour.b + (((oldColour.b - newColour.b) * blendAmount) >> 8);
			blended.a = newColour.a + (((oldColour.a - newColour.a) * blendAmount) >> 8);

			uint16_t& pixel = pixels[destinationV * textureWidth + destinationU];
			int       inverseAlpha = LH3D_COLOR_OPAQUE - blended.a;
			int       red = (((pixel >> 4) & 0xf0) * inverseAlpha + blended.r * blended.a) / LH3D_COLOR_OPAQUE;
			int       green = ((pixel & 0xf0) * inverseAlpha + blended.g * blended.a) / LH3D_COLOR_OPAQUE;
			int       blue = (((pixel & 0xf) << 4) * inverseAlpha + blended.b * blended.a) / LH3D_COLOR_OPAQUE;
			pixel = 0xf000 | ((red & 0xf0) << 4) | (green & 0xf0) | ((blue >> 4) & 0xf);
		}
	}

	texture->Unlock();
	uint32_t textureType = texture->GetType();
	if (textureType == LH3D_TEXTURE_TYPE_NAMED || textureType == LH3D_TEXTURE_TYPE_SYSTEM_MEMORY)
	{
		texture->ReloadPending = true;
	}
}
