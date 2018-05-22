# This environment is created by Alexander Clegg (alexanderwclegg@gmail.com)
# Phase interpolate2: end of 1st sleeve to match grip

import numpy as np
from gym import utils
from gym.envs.dart.dart_cloth_env import *
from gym.envs.dart.upperbodydatadriven_cloth_base import *
import random
import time
import math

from pyPhysX.colors import *
import pyPhysX.pyutils as pyutils
from pyPhysX.pyutils import LERP
import pyPhysX.renderUtils
import pyPhysX.meshgraph as meshgraph
from pyPhysX.clothfeature import *

import OpenGL.GL as GL
import OpenGL.GLU as GLU
import OpenGL.GLUT as GLUT

class DartClothUpperBodyDataDrivenClothPhaseInterpolate2Env(DartClothUpperBodyDataDrivenClothBaseEnv, utils.EzPickle):
    def __init__(self):
        #feature flags
        rendering = True
        clothSimulation = True
        renderCloth = True

        #observation terms
        self.contactIDInObs = True  # if true, contact ids are in obs
        self.hapticsInObs   = True  # if true, haptics are in observation
        self.prevTauObs     = False  # if true, previous action in observation

        #reward flags
        self.uprightReward              = True #if true, rewarded for 0 torso angle from vertical
        self.stableHeadReward           = True  # if True, rewarded for - head/torso angle
        self.elbowFlairReward           = False
        self.deformationPenalty         = True
        self.restPoseReward             = True
        self.restCOMsReward             = False  # if True, penalize displacement between world targets and the positions of local offsets
        self.rightTargetReward          = True
        self.taskReward                 = True #if true, an additional reward is provided when the EF is within task success distance of the target
        self.leftTargetReward           = False
        self.efTargetRewardTiering      = False
        self.rightTargetAltitudeReward  = False #penalize right hand lower than target #TODO: necessary?
        self.elbowElevationReward       = False  # if true, penalize elbow about hte shoulders
        self.aliveBonus                 = True
        self.bicepInReward              = False #penalize the active bicep for point away from the other arm

        # reward weights
        self.uprightRewardWeight = 2
        self.stableHeadRewardWeight = 2
        self.elbowFlairRewardWeight = 1
        self.deformationPenaltyWeight = 15  # was 5...
        self.restPoseRewardWeight = 2
        self.restCOMsRewardWeight = 10
        self.leftTargetRewardWeight = 50
        self.rightTargetRewardWeight = 100
        self.elbowElevationRewardWeight = 10
        self.aliveBonusWeight           = 80#160
        self.bicepInRewardWeight        = 30

        #other flags
        self.elbowElevationTermination = False
        self.elbowTerminationElevation = 0.1
        self.collarTermination = True  # if true, rollout terminates when collar is off the head/neck
        self.collarTerminationCD = 0 #number of frames to ignore collar at the start of simulation (gives time for the cloth to drop)
        self.hapticsAware       = True  # if false, 0's for haptic input
        self.loadTargetsFromROMPositions = False
        self.resetPoseFromROMPoints = False
        self.resetTime = 0
        self.resetStateFromDistribution = True
        #self.resetDistributionPrefix = "saved_control_states/sleeveR"
        #self.resetDistributionSize = 17#2
        self.resetDistributionPrefix = "saved_control_states/enter_seq_match"
        self.resetDistributionSize = 20

        #other variables
        self.handleNode = None
        self.updateHandleNodeFrom = 12  # left fingers
        self.prevTau = None
        self.maxDeformation = 30.0
        self.restPose = None
        self.restCOMs = []
        self.localRightEfShoulder1 = None
        self.localLeftEfShoulder1 = None
        self.rightTarget = np.zeros(3)
        self.leftTarget = np.zeros(3)
        self.prevErrors = None #stores the errors taken from DART each iteration
        self.previousDeformationReward = 0
        self.fingertip = np.array([0, -0.09, 0])

        self.actuatedDofs = np.arange(22)
        observation_size = len(self.actuatedDofs)*3 #q(sin,cos), dq
        if self.prevTauObs:
            observation_size += len(self.actuatedDofs)
        if self.hapticsInObs:
            observation_size += 66
        if self.contactIDInObs:
            observation_size += 22
        if self.rightTargetReward:
            observation_size += 9
        if self.leftTargetReward:
            observation_size += 9

        DartClothUpperBodyDataDrivenClothBaseEnv.__init__(self,
                                                          rendering=rendering,
                                                          screensize=(1280,720),
                                                          clothMeshFile="tshirt_m.obj",
                                                          clothMeshStateFile = "objFile_1starmin.obj",
                                                          clothScale=1.4,
                                                          obs_size=observation_size,
                                                          simulateCloth=clothSimulation)

        # clothing features
        self.collarVertices = [117, 115, 113, 900, 108, 197, 194, 8, 188, 5, 120]
        #self.targetGripVertices = [570, 1041, 285, 1056, 435, 992, 50, 489, 787, 327, 362, 676, 887, 54, 55]
        self.targetGripVerticesL = [46, 437, 955, 1185, 47, 285, 711, 677, 48, 905, 1041, 49, 741, 889, 45]
        self.targetGripVerticesR = [905, 1041, 49, 435, 50, 570, 992, 1056, 51, 676, 283, 52, 489, 892, 362, 53]
        self.gripFeatureL = ClothFeature(verts=self.targetGripVerticesL, clothScene=self.clothScene, b1spanverts=[889,1041], b2spanverts=[47,677])
        self.gripFeatureR = ClothFeature(verts=self.targetGripVerticesR, clothScene=self.clothScene, b1spanverts=[362,889], b2spanverts=[51,992])

        self.collarFeature = ClothFeature(verts=self.collarVertices, clothScene=self.clothScene)

        self.simulateCloth = clothSimulation
        if self.simulateCloth:
            self.handleNode = HandleNode(self.clothScene, org=np.array([0.05, 0.034, -0.975]))

        if not renderCloth:
            self.clothScene.renderClothFill = False
            self.clothScene.renderClothBoundary = False
            self.clothScene.renderClothWires = False

        # load rewards into the RewardsData structure
        if self.uprightReward:
            self.rewardsData.addReward(label="upright", rmin=-2.5, rmax=0, rval=0, rweight=self.uprightRewardWeight)

        if self.stableHeadReward:
            self.rewardsData.addReward(label="stable head",rmin=-1.2,rmax=0,rval=0, rweight=self.stableHeadRewardWeight)

        if self.deformationPenalty:
            self.rewardsData.addReward(label="deformation", rmin=-1.0, rmax=0, rval=0, rweight=self.deformationPenaltyWeight)

        if self.restPoseReward:
            self.rewardsData.addReward(label="rest pose", rmin=-51.0, rmax=0, rval=0, rweight=self.restPoseRewardWeight)

        if self.restCOMsReward:
            self.rewardsData.addReward(label="rest COMs", rmin=-20.0, rmax=0, rval=0, rweight=self.restCOMsRewardWeight)

        if self.leftTargetReward:
            self.rewardsData.addReward(label="efL", rmin=-1.0, rmax=0, rval=0, rweight=self.leftTargetRewardWeight)

        if self.rightTargetReward:
            if self.taskReward:
                self.rewardsData.addReward(label="efR(task)", rmin=-2.0, rmax=0.05, rval=0, rweight=self.rightTargetRewardWeight)
            else:
                self.rewardsData.addReward(label="efR", rmin=-2.0, rmax=0, rval=0, rweight=self.rightTargetRewardWeight)

        if self.elbowElevationReward:
            self.rewardsData.addReward(label="elbow elevation", rmin=-1.0, rmax=0.0, rval=0, rweight=self.elbowElevationRewardWeight)

        if self.aliveBonus:
            self.rewardsData.addReward(label="alive bonus", rmin=0.0, rmax=1.0, rval=0, rweight=self.aliveBonusWeight)

        if self.bicepInReward:
            self.rewardsData.addReward(label="bicep in", rmin=-1.0, rmax=1.0, rval=0, rweight=self.bicepInRewardWeight)


        self.state_save_directory = "saved_control_states/"
        self.saveStateOnReset = False

    def _getFile(self):
        return __file__

    def updateBeforeSimulation(self):
        #any pre-sim updates should happen here
        wRFingertip1 = self.robot_skeleton.bodynodes[7].to_world(self.fingertip)
        wLFingertip1 = self.robot_skeleton.bodynodes[12].to_world(self.fingertip)
        self.localRightEfShoulder1 = self.robot_skeleton.bodynodes[3].to_local(wRFingertip1)  # right fingertip in right shoulder local frame
        self.localLeftEfShoulder1 = self.robot_skeleton.bodynodes[8].to_local(wLFingertip1)  # left fingertip in left shoulder local frame
        self.rightTarget = pyutils.getVertCentroid(verts=self.targetGripVerticesR, clothscene=self.clothScene) + pyutils.getVertAvgNorm(verts=self.targetGripVerticesR, clothscene=self.clothScene)*0.03

        if self.collarFeature is not None:
            self.collarFeature.fitPlane()
        self.gripFeatureL.fitPlane()
        self.gripFeatureR.fitPlane()

        # update handle nodes
        if self.handleNode is not None:
            if self.updateHandleNodeFrom >= 0:
                self.handleNode.setTransform(self.robot_skeleton.bodynodes[self.updateHandleNodeFrom].T)
            self.handleNode.step()

        #self.rightTarget = self.robot_skeleton.bodynodes[12].to_world(fingertip)

        a=0

    def checkTermination(self, tau, s, obs):
        #check the termination conditions and return: done,reward
        topHead = self.robot_skeleton.bodynodes[14].to_world(np.array([0, 0.25, 0]))
        bottomHead = self.robot_skeleton.bodynodes[14].to_world(np.zeros(3))
        bottomNeck = self.robot_skeleton.bodynodes[13].to_world(np.zeros(3))

        if np.amax(np.absolute(s[:len(self.robot_skeleton.q)])) > 10:
            print("Detecting potential instability")
            print(s)
            return True, -2500
        elif not np.isfinite(s).all():
            print("Infinite value detected..." + str(s))
            return True, -2500

        if self.collarTermination and self.simulateCloth and self.collarTerminationCD < self.numSteps:
            if not (self.collarFeature.contains(l0=bottomNeck, l1=bottomHead)[0] or
                        self.collarFeature.contains(l0=bottomHead, l1=topHead)[0]):
                #print("collar term")
                return True, -2500

        if self.numSteps == 60:#99:
            if self.saveStateOnReset and self.reset_number > 0:
                fname = self.state_save_directory + "matchgrip_reduced"
                print(fname)
                count = 0
                objfname_ix = fname + "%05d" % count
                charfname_ix = fname + "_char%05d" % count
                while os.path.isfile(objfname_ix + ".obj"):
                    count += 1
                    objfname_ix = fname + "%05d" % count
                    charfname_ix = fname + "_char%05d" % count
                print(objfname_ix)
                self.saveObjState(filename=objfname_ix)
                self.saveCharacterState(filename=charfname_ix)

        if self.elbowElevationTermination:
            shoulderR = self.robot_skeleton.bodynodes[4].to_world(np.zeros(3))
            shoulderL = self.robot_skeleton.bodynodes[9].to_world(np.zeros(3))
            elbow = self.robot_skeleton.bodynodes[5].to_world(np.zeros(3))
            shoulderR_torso = self.robot_skeleton.bodynodes[1].to_local(shoulderR)
            shoulderL_torso = self.robot_skeleton.bodynodes[1].to_local(shoulderL)
            elbow_torso = self.robot_skeleton.bodynodes[1].to_local(elbow)

            elevation = 0
            if elbow_torso[1] > shoulderL_torso[1] or elbow[1] > shoulderR_torso[1]:
                elevation = max(elbow_torso[1] - shoulderL_torso[1], elbow_torso[1] - shoulderR_torso[1])

            if elevation > self.elbowTerminationElevation:
                return True, -2500

        return False, 0

    def computeReward(self, tau):
        #compute and return reward at the current state
        wRFingertip2 = self.robot_skeleton.bodynodes[7].to_world(self.fingertip)
        wLFingertip2 = self.robot_skeleton.bodynodes[12].to_world(self.fingertip)
        localRightEfShoulder2 = self.robot_skeleton.bodynodes[3].to_local(wRFingertip2)  # right fingertip in right shoulder local frame
        localLeftEfShoulder2 = self.robot_skeleton.bodynodes[8].to_local(wLFingertip2)  # right fingertip in right shoulder local frame

        #store the previous step's errors
        #if self.reset_number > 0 and self.numSteps > 0:
        #    self.prevErrors = self.dart_world.getAllConstraintViolations()
            #print("after getAllCon..")
            #print("prevErrors: " +str(self.prevErrors))

        reward_record = []

        self.prevTau = tau

        clothDeformation = 0
        if self.simulateCloth:
            clothDeformation = self.clothScene.getMaxDeformationRatio(0)
            self.deformation = clothDeformation

        # force magnitude penalty
        reward_ctrl = -np.square(tau).sum()

        # reward for maintaining posture
        reward_upright = 0
        if self.uprightReward:
            reward_upright = max(-2.5, -abs(self.robot_skeleton.q[0]) - abs(self.robot_skeleton.q[1]))
            reward_record.append(reward_upright)

        reward_stableHead = 0
        if self.stableHeadReward:
            reward_stableHead = max(-1.2, -abs(self.robot_skeleton.q[19]) - abs(self.robot_skeleton.q[20]))
            reward_record.append(reward_stableHead)

        reward_clothdeformation = 0
        if self.deformationPenalty is True:
            # reward_clothdeformation = (math.tanh(9.24 - 0.5 * clothDeformation) - 1) / 2.0  # near 0 at 15, ramps up to -1.0 at ~22 and remains constant
            reward_clothdeformation = -(math.tanh(
                0.14 * (clothDeformation - 25)) + 1) / 2.0  # near 0 at 15, ramps up to -1.0 at ~22 and remains constant
            reward_record.append(reward_clothdeformation)
        self.previousDeformationReward = reward_clothdeformation

        reward_restPose = 0
        if self.restPoseReward and self.restPose is not None:
            '''z = 0.5  # half the max magnitude (e.g. 0.5 -> [0,1])
            s = 1.0  # steepness (higher is steeper)
            l = 4.2  # translation
            dist = np.linalg.norm(self.robot_skeleton.q - self.restPose)
            reward_restPose = -(z * math.tanh(s * (dist - l)) + z)'''
            dist = np.linalg.norm(self.robot_skeleton.q - self.restPose)
            reward_restPose = max(-51, -dist)
            reward_record.append(reward_restPose)
            # print("distance: " + str(dist) + " -> " + str(reward_restPose))

        reward_restCOMs = 0
        if self.restCOMsReward:
            for ix, b in enumerate(self.robot_skeleton.bodynodes):
                reward_restCOMs -= np.linalg.norm(self.restCOMs[ix] - b.com())
            reward_restCOMs = max(reward_restCOMs, -20)
            reward_record.append(reward_restCOMs)

        reward_leftTarget = 0
        if self.leftTargetReward:
            lDist = np.linalg.norm(self.leftTarget - wLFingertip2)
            #reward_leftTarget = -lDist - lDist ** 2
            reward_leftTarget = -lDist
            if self.efTargetRewardTiering:
                if lDist > 0.1:
                    reward_leftTarget -= 0.5
            reward_record.append(reward_leftTarget)
            '''if lDist < 0.02:
                reward_leftTarget += 0.25'''

        reward_rightTarget = 0
        if self.rightTargetReward:
            lDist = np.linalg.norm(self.leftTarget - wLFingertip2)
            rDist = np.linalg.norm(self.rightTarget-wRFingertip2)
            #reward_rightTarget = -rDist - rDist**2
            reward_rightTarget = -rDist
            if self.taskReward:
                if rDist < 0.02:
                    reward_rightTarget += 0.05
            if self.efTargetRewardTiering:
                if lDist > 0.1:
                    reward_rightTarget = -1
                elif rDist > 0.1:
                    reward_rightTarget = -0.5
            reward_record.append(reward_rightTarget)
            '''if rDist < 0.02:
                reward_rightTarget += 0.25'''

        reward_rightTargetAltitude = 0
        if self.rightTargetAltitudeReward:
            reward_rightTargetAltitude = -(self.rightTarget[1]-wRFingertip2[1])
            if reward_rightTargetAltitude > 0:
                reward_rightTargetAltitude = 0
            else:
                reward_rightTargetAltitude -= 0.5
            #print(reward_rightTargetAltitude)

        reward_elbowElevation = 0
        if self.elbowElevationReward:
            shoulderR = self.robot_skeleton.bodynodes[4].to_world(np.zeros(3))
            shoulderL = self.robot_skeleton.bodynodes[9].to_world(np.zeros(3))
            elbow = self.robot_skeleton.bodynodes[5].to_world(np.zeros(3))
            shoulderR_torso = self.robot_skeleton.bodynodes[1].to_local(shoulderR)
            shoulderL_torso = self.robot_skeleton.bodynodes[1].to_local(shoulderL)
            elbow_torso = self.robot_skeleton.bodynodes[1].to_local(elbow)

            if elbow_torso[1] > shoulderL_torso[1] or elbow[1] > shoulderR_torso[1]:
                reward_elbowElevation = -max(elbow_torso[1] - shoulderL_torso[1], elbow_torso[1] - shoulderR_torso[1])
            reward_record.append(reward_elbowElevation)

        reward_alive = 0
        if self.aliveBonus:
            reward_alive = 1.0
            reward_record.append(reward_alive)

        reward_bicepIn = 0
        if self.bicepInReward:
            bicep_up = self.robot_skeleton.bodynodes[4].to_world(np.array([0.0, -0.15, -0.075])) - self.robot_skeleton.bodynodes[4].to_world(np.array([0.0, -0.15, 0]))
            bicep_up = bicep_up / np.linalg.norm(bicep_up)
            passiveElbow = self.robot_skeleton.bodynodes[10].com() #acutally the joint
            targetDir = passiveElbow - self.robot_skeleton.bodynodes[4].to_world(np.array([0.0, -0.15, 0]))
            targetDir = targetDir/np.linalg.norm(targetDir)
            reward_bicepIn = bicep_up.dot(targetDir)
            reward_record.append(reward_bicepIn)

        # update the reward data storage
        self.rewardsData.update(rewards=reward_record)

        #print("reward_restPose: " + str(reward_restPose))
        #print("reward_leftTarget: " + str(reward_leftTarget))
        self.reward = reward_ctrl * 0 \
                      + reward_upright * self.uprightRewardWeight \
                      + reward_stableHead * self.stableHeadRewardWeight \
                      + reward_clothdeformation * self.deformationPenaltyWeight \
                      + reward_restPose * self.restPoseRewardWeight \
                      + reward_rightTarget * self.rightTargetRewardWeight \
                      + reward_leftTarget * self.leftTargetRewardWeight \
                      + reward_rightTargetAltitude*4 \
                      + reward_elbowElevation * self.elbowElevationRewardWeight \
                      + reward_alive * self.aliveBonusWeight \
                      + reward_bicepIn * self.bicepInRewardWeight \
                      + reward_restCOMs * self.restCOMsRewardWeight

        # TODO: revisit the deformation penalty
        return self.reward

    def _get_obs(self):
        f_size = 66
        '22x3 dofs, 22x3 sensors, 7x2 targets(toggle bit, cartesian, relative)'
        theta = np.zeros(len(self.actuatedDofs))
        dtheta = np.zeros(len(self.actuatedDofs))
        for ix, dof in enumerate(self.actuatedDofs):
            theta[ix] = self.robot_skeleton.q[dof]
            dtheta[ix] = self.robot_skeleton.dq[dof]

        obs = np.concatenate([np.cos(theta), np.sin(theta), dtheta]).ravel()

        if self.prevTauObs:
            obs = np.concatenate([obs, self.prevTau])

        if self.hapticsInObs:
            f = None
            if self.simulateCloth and self.hapticsAware:
                f = self.clothScene.getHapticSensorObs()#get force from simulation
            else:
                f = np.zeros(f_size)
            obs = np.concatenate([obs, f]).ravel()

        if self.contactIDInObs:
            HSIDs = self.clothScene.getHapticSensorContactIDs()
            obs = np.concatenate([obs, HSIDs]).ravel()

        if self.rightTargetReward:
            efR = self.robot_skeleton.bodynodes[7].to_world(self.fingertip)
            obs = np.concatenate([obs, self.rightTarget, efR, self.rightTarget-efR]).ravel()

        if self.leftTargetReward:
            efL = self.robot_skeleton.bodynodes[12].to_world(self.fingertip)
            obs = np.concatenate([obs, self.leftTarget, efL, self.leftTarget-efL]).ravel()

        return obs

    def additionalResets(self):
        '''if self.resetTime > 0:
            print("reset " + str(self.reset_number) + " after " + str(time.time()-self.resetTime))
        '''
        self.resetTime = time.time()
        #do any additional resetting here
        '''if self.simulateCloth:
            up = np.array([0,1.0,0])
            varianceR = pyutils.rotateY(((random.random()-0.5)*2.0)*0.3)
            adjustR = pyutils.rotateY(0.2)
            R = self.clothScene.rotateTo(v1=np.array([0,0,1.0]), v2=up)
            self.clothScene.translateCloth(0, np.array([-0.01, 0.0255, 0]))
            self.clothScene.rotateCloth(cid=0, R=R)
            self.clothScene.rotateCloth(cid=0, R=adjustR)
            self.clothScene.rotateCloth(cid=0, R=varianceR)'''
        qvel = self.robot_skeleton.dq + self.np_random.uniform(low=-0.1, high=0.1, size=self.robot_skeleton.ndofs)

        '''if self.resetPoseFromROMPoints and len(self.ROMPoints) > 0:
            poseFound = False
            while not poseFound:
                ix = random.randint(0,len(self.ROMPoints)-1)
                qpos = self.ROMPoints[ix]
                efR = self.ROMPositions[ix][:3]
                efL = self.ROMPositions[ix][-3:]
                if efR[2] < 0 and efL[2] < 0: #half-plane constraint on end effectors
                    poseFound = True
        '''
        #Check the constrained population
        '''positive = 0
        for targets in self.ROMPositions:
            efR = targets[:3]
            efL = targets[-3:]
            if efR[2] < 0 and efL[2] < 0:
                positive += 1
        print("Valid Poses: " + str(positive) + " | ratio: " + str(positive/len(self.ROMPositions)))'''


        '''if self.loadTargetsFromROMPositions and len(self.ROMPositions) > 0:
            targetFound = False
            while not targetFound:
                ix = random.randint(0, len(self.ROMPositions) - 1)
                self.rightTarget = self.ROMPositions[ix][:3] + self.np_random.uniform(low=-0.01, high=0.01, size=3)
                self.leftTarget = self.ROMPositions[ix][-3:] + self.np_random.uniform(low=-0.01, high=0.01, size=3)
                if self.rightTarget[2] < 0 and self.leftTarget[2] < 0: #half-plane constraint on end effectors
                    targetFound = True
        self.set_state(qpos, qvel)'''

        #self.loadCharacterState(filename="characterState_regrip")

        #find end effector targets and set restPose from solution

        #print("left target: " + str(self.leftTarget))
        #self.restPose = np.array(self.robot_skeleton.q)
        self.restPose = np.array([-0.210940942604, -0.0602436241858, 0.785540563981, 0.132571030392, -0.25, -0.580739841458, -0.803858324899, -1.472, 1.27301394196, -0.295286198863, 0.611311245326, 0.245333463513, 0.225511476131, 1.20063053643, -0.0501794921426, 1.19122509695, 1.97519722198, -0.573360432341, 0.321222466527, 0.580323061076, -0.422112755785, -0.997819593165])
        self.robot_skeleton.set_positions(self.restPose)
        self.leftTarget = self.robot_skeleton.bodynodes[12].to_world(self.fingertip)

        self.restCOMs = []
        for b in self.robot_skeleton.bodynodes:
            self.restCOMs.append(b.com())

        if self.resetStateFromDistribution:
            if self.reset_number == 0: #load the distribution
                count = 0
                objfname_ix = self.resetDistributionPrefix + "%05d" % count
                while os.path.isfile(objfname_ix + ".obj"):
                    count += 1
                    #print(objfname_ix)
                    self.clothScene.addResetStateFrom(filename=objfname_ix+".obj")
                    objfname_ix = self.resetDistributionPrefix + "%05d" % count

            resetStateNumber = random.randint(0,self.resetDistributionSize-1)
            #resetStateNumber = self.reset_number % self.resetDistributionSize
            #resetStateNumber = 15
            #print("resetStateNumber: " + str(resetStateNumber))
            charfname_ix = self.resetDistributionPrefix + "_char%05d" % resetStateNumber
            self.clothScene.setResetState(cid=0, index=resetStateNumber)
            self.loadCharacterState(filename=charfname_ix)
            qvel = self.robot_skeleton.dq + self.np_random.uniform(low=-0.2, high=0.2, size=self.robot_skeleton.ndofs)
            self.robot_skeleton.set_velocities(qvel)

        else:
            self.loadCharacterState(filename="characterState_1starmin")

        if self.handleNode is not None:
            self.handleNode.clearHandles()
            self.handleNode.addVertices(verts=self.targetGripVerticesL)
            self.handleNode.setOrgToCentroid()
            if self.updateHandleNodeFrom >= 0:
                self.handleNode.setTransform(self.robot_skeleton.bodynodes[self.updateHandleNodeFrom].T)
            self.handleNode.recomputeOffsets()

        self.rightTarget = pyutils.getVertCentroid(verts=self.targetGripVerticesR, clothscene=self.clothScene) + pyutils.getVertAvgNorm(verts=self.targetGripVerticesR, clothscene=self.clothScene)*0.03


        if self.simulateCloth:
            self.collarFeature.fitPlane()
            self.gripFeatureL.fitPlane(normhint=np.array([0,0,1]))
            self.gripFeatureR.fitPlane(normhint=np.array([0,0,1]))
        a=0

    def extraRenderFunction(self):
        renderUtils.setColor(color=[0.0, 0.0, 0])
        GL.glBegin(GL.GL_LINES)
        GL.glVertex3d(0,0,0)
        GL.glVertex3d(-1,0,0)
        GL.glEnd()

        topHead = self.robot_skeleton.bodynodes[14].to_world(np.array([0, 0.25, 0]))
        bottomHead = self.robot_skeleton.bodynodes[14].to_world(np.zeros(3))
        bottomNeck = self.robot_skeleton.bodynodes[13].to_world(np.zeros(3))

        renderUtils.drawLineStrip(points=[bottomNeck, bottomHead, topHead])
        if self.collarFeature is not None:
            self.collarFeature.drawProjectionPoly(renderNormal=False, renderBasis=False)

        self.gripFeatureL.drawProjectionPoly(renderNormal=False, renderBasis=False, fillColor=[1,0,0])
        self.gripFeatureR.drawProjectionPoly(renderNormal=True, renderBasis=False, fillColor=[0,1,0], vecLenScale=0.1)

        renderUtils.setColor([0,0,0])
        renderUtils.drawLineStrip(points=[self.robot_skeleton.bodynodes[4].to_world(np.array([0.0,0,-0.075])), self.robot_skeleton.bodynodes[4].to_world(np.array([0.0,-0.3,-0.075]))])
        renderUtils.drawLineStrip(points=[self.robot_skeleton.bodynodes[9].to_world(np.array([0.0,0,-0.075])), self.robot_skeleton.bodynodes[9].to_world(np.array([0.0,-0.3,-0.075]))])

        # rest COMs
        renderUtils.setColor(color=[1.0,1.0,0])
        restCOMsLines = []
        if self.restCOMsReward:
            for ix, b in enumerate(self.robot_skeleton.bodynodes):
                restCOMsLines.append([b.com(), self.restCOMs[ix]])
        renderUtils.drawLines(restCOMsLines)

        renderUtils.setColor([0, 0, 0])
        if self.bicepInReward:
            bicep_top = self.robot_skeleton.bodynodes[4].to_world(np.array([0.0, -0.15, -0.075]))
            bicep_core = self.robot_skeleton.bodynodes[4].to_world(np.array([0.0, -0.15, 0]))
            bicep_up = bicep_top-bicep_core
            bicep_up = bicep_up / np.linalg.norm(bicep_up)
            passiveElbow = self.robot_skeleton.bodynodes[10].com()  # acutally the joint
            targetDir = passiveElbow - self.robot_skeleton.bodynodes[4].to_world(np.array([0.0, -0.15, 0]))
            targetDir = targetDir / np.linalg.norm(targetDir)
            renderUtils.drawLines(lines=[[passiveElbow, bicep_core], [bicep_core, bicep_top]])

        if self.restPoseReward:
            renderUtils.drawLines(pyutils.getRobotLinks(self.robot_skeleton,self.restPose))

        #render targets
        if self.rightTargetReward:
            efR = self.robot_skeleton.bodynodes[7].to_world(self.fingertip)
            renderUtils.setColor(color=[1.0,0,0])
            if self.efTargetRewardTiering:
                renderUtils.drawSphere(pos=self.rightTarget,rad=0.1, solid=False)
            renderUtils.drawSphere(pos=self.rightTarget,rad=0.02)
            renderUtils.drawLineStrip(points=[self.rightTarget, efR])
        if self.leftTargetReward:
            efL = self.robot_skeleton.bodynodes[12].to_world(self.fingertip)
            renderUtils.setColor(color=[0, 1.0, 0])
            renderUtils.drawSphere(pos=self.leftTarget,rad=0.02)
            if self.efTargetRewardTiering:
                renderUtils.drawSphere(pos=self.leftTarget,rad=0.1, solid=False)
            renderUtils.drawLineStrip(points=[self.leftTarget, efL])

        m_viewport = self.viewer.viewport
        self.rewardsData.render(topLeft=[m_viewport[2]-410,m_viewport[3]-15], dimensions=[400, -m_viewport[3]+30])


        textHeight = 15
        textLines = 2

        if self.renderUI:
            renderUtils.setColor(color=[0.,0,0])
            self.clothScene.drawText(x=15., y=textLines*textHeight, text="Steps = " + str(self.numSteps), color=(0., 0, 0))
            textLines += 1
            self.clothScene.drawText(x=15., y=textLines*textHeight, text="Reward = " + str(self.reward), color=(0., 0, 0))
            textLines += 1
            self.clothScene.drawText(x=15., y=textLines * textHeight, text="Cumulative Reward = " + str(self.cumulativeReward), color=(0., 0, 0))
            textLines += 1
            if self.numSteps > 0:
                renderUtils.renderDofs(robot=self.robot_skeleton, restPose=self.restPose, renderRestPose=True)

            renderUtils.drawProgressBar(topLeft=[600, self.viewer.viewport[3] - 30], h=16, w=60, progress=-self.previousDeformationReward, color=[1.0, 0.0, 0])
