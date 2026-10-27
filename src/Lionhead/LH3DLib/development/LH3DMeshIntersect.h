#ifndef BW1_DECOMP_LH3D_MESH_INTERSECT_INCLUDED_H
#define BW1_DECOMP_LH3D_MESH_INTERSECT_INCLUDED_H

#include <assert.h> /* For static_assert */
#include <stdint.h> /* For uint32_t */

#include <re_common.h> /* For bool32_t */

#define SCAR_TEXTURE_SIZE                256
#define SCAR_TILE_SIZE                   32
#define SCAR_SMALL_TEXTURE_SIZE          (SCAR_TEXTURE_SIZE / 2)
#define MESH_INTERSECT_MAX_VERTICES      4096
#define MESH_INTERSECT_TRIANGLE_VERTICES 3
#define MESH_INTERSECT_PARALLEL_EPSILON  0.005f
#define MESH_INTERSECT_FACING_EPSILON    -0.0001f
#define MESH_INTERSECT_UV_EPSILON        0.0001f
#define MESH_INTERSECT_SEARCH_MARGIN     50.0f

struct LH3DColor;
struct LH3DMesh;
class LHFile;
struct LHMatrix;
struct LHPoint;

struct MeshIntersectData
{
	LHPoint* WorldPoints;
	uint32_t (*WorldTris)[MESH_INTERSECT_TRIANGLE_VERTICES];
	int TriangleCount;
};

struct TextureRef
{
	union {
		uint16_t Position;
		struct
		{
			uint8_t U;
			uint8_t V;
		};
	};
	uint16_t Age : 6;
	uint16_t Skin : 2;
	uint16_t Type : 3;
	uint16_t SubType : 3;
	uint16_t Flags : 2;

	// BW1W120 00867040 BW1M119 0106e190 (LHCombined Release)
	void DrawCutAroundIntersectionPoint(LH3DMesh* mesh, float age);
	// BW1W120 00866d00 BW1M119 0106e860 (LHCombined Release)
	void ColourIntersectionPoint(LH3DMesh* mesh, LH3DColor* colour, float blend);
};

struct MeshIntersect
{
	// BW1W120 00865000 BW1M119 01070130 (LHCombined Release)
	static void InitialiseMeshIntersect();
	uint32_t    PrimitiveIndex;
	uint32_t    SubmeshIndex;
	uint32_t    VertexIndices[MESH_INTERSECT_TRIANGLE_VERTICES];
	uint32_t    VertexGroupIndices[MESH_INTERSECT_TRIANGLE_VERTICES];
	float       Beta;
	float       Gamma;

	// BW1W120 00866a90 BW1M119 0106ed00 (LHCombined Release)
	void GetTextureRef(LH3DMesh* mesh, TextureRef* ref);
	// BW1W120 00866ba0 BW1M119 0106eae0 (LHCombined Release)
	void ObtainPointColour(LH3DMesh* mesh, unsigned long* colour);
	// BW1W120 00867c20 BW1M119 0106d370 (LHCombined Release)
	void ReadBinary(LHFile* file);
	// BW1W120 00867b50 BW1M119 0106d580 (LHCombined Release)
	void WriteBinary(LHFile* file);
	// BW1W120 00865020 BW1M119 01035620 (LHCombined Release)
	bool32_t GetNearestIntersection(LH3DMesh* mesh, const LHMatrix* matrices, LHPoint* start, LHPoint* direction,
	                                bool collision_only, LHPoint* impact, LHPoint* inward_normal, bool both_directions);
	// BW1W120 00865a20 BW1M119 0106fd80 (LHCombined Release)
	static void SetUpWorldPoints(LH3DMesh* mesh, const LHMatrix* matrices, MeshIntersectData* data);
	// BW1W120 00865d00 BW1M119 0106f7c0 (LHCombined Release)
	static bool32_t GetImpactPointAlex(LHPoint& start, LHPoint& direction, LHPoint& impact, LHPoint& normal,
	                                   MeshIntersectData* data, float limit);
	// BW1W120 00866260 BW1M119 0106f320 (LHCombined Release)
	static bool32_t GetImpactPoint(LHPoint& start, LHPoint& direction, LHPoint& impact, LHPoint& normal,
	                               MeshIntersectData* data);
	// BW1W120 00866640 BW1M119 0106eea0 (LHCombined Release)
	bool32_t CreateFromTextureRef(LH3DMesh* mesh, LHMatrix* matrices, TextureRef* ref);
	// BW1W120 00867400 BW1M119 0106dce0 (LHCombined Release)
	void GetWorldPositionAndInwardNormal(LH3DMesh* mesh, const LHMatrix* matrices, LHPoint* position, LHPoint* normal);
	// BW1W120 00867740 BW1M119 0106d6d0 (LHCombined Release)
	void GetWorldPositionInwardNormalAndAverageMatrix(LH3DMesh* mesh, const LHMatrix* matrices, LHPoint* position,
	                                                  LHPoint* normal, LHMatrix* average);
};

struct CollideBox
{
	// BW1W120 00867fe0 BW1M119 01047970 (LHCombined Release)
	void InitForCollision(LH3DMesh* mesh, LHMatrix* matrices);
	// BW1W120 008683c0 BW1M119 010ad410 (LHCombined Release)
	bool32_t GetImpactPoint(LH3DMesh* mesh, LHPoint& start, LHPoint& direction, LHPoint& impact, LHPoint& normal);
};

#endif /* BW1_DECOMP_LH3D_MESH_INTERSECT_INCLUDED_H */
