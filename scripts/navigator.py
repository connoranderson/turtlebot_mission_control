#!/usr/bin/env python

import rospy
from nav_msgs.msg import OccupancyGrid
from nav_msgs.msg import MapMetaData
import numpy as np
import matplotlib.pyplot as plt
import tf
from std_msgs.msg import Float32MultiArray
from astar import AStar, DetOccupancyGrid2D, StochOccupancyGrid2D
from nav_msgs.msg import Path
from geometry_msgs.msg import PoseStamped

import pdb


class Navigator:
    def __init__(self):
        rospy.init_node('turtlebot_navigator', anonymous=True)

        self.plan_resolution = 0.25
        self.plan_horizon = 15

        self.map_width = 0
        self.map_height = 0
        self.map_resolution = 0
        self.map_origin = [0, 0]
        self.map_probs = []
        self.occupancy = None

        self.nav_sp = None
        self.trans_listener = tf.TransformListener()

        rospy.Subscriber("map", OccupancyGrid, self.map_callback)
        rospy.Subscriber("map_metadata", MapMetaData, self.map_md_callback)
        rospy.Subscriber("/turtlebot_controller/nav_goal", Float32MultiArray, self.nav_sp_callback)

        self.pose_sp_pub = rospy.Publisher('/turtlebot_controller/position_goal', Float32MultiArray, queue_size=10)
        self.nav_path_pub = rospy.Publisher('/turtlebot_controller/path_goal', Path, queue_size=10)

    def map_md_callback(self,msg):
        self.map_width = msg.width
        self.map_height = msg.height
        self.map_resolution = msg.resolution
        self.map_origin = (msg.origin.position.x,msg.origin.position.y)

    def map_callback(self,msg):
        self.map_probs = msg.data
        if self.map_width>0 and self.map_height>0 and len(self.map_probs)>0:
            self.occupancy = StochOccupancyGrid2D(self.map_resolution,
                                                  self.map_width,
                                                  self.map_height,
                                                  self.map_origin[0],
                                                  self.map_origin[1],
                                                  int(self.plan_resolution / self.map_resolution) * 2,
                                                  self.map_probs)

    def nav_sp_callback(self,msg):
        self.nav_sp = (msg.data[0],msg.data[1],msg.data[2])
        self.send_pose_sp()

    def send_pose_sp(self):
        try:
            (robot_translation,
             robot_rotation) = self.trans_listener.lookupTransform("/map","/base_footprint",rospy.Time(0))
            self.has_robot_location = True
        except (tf.LookupException, tf.ConnectivityException,
                tf.ExtrapolationException):
            robot_translation = (0, 0, 0)
            robot_rotation = (0, 0, 0, 1)
            self.has_robot_location = False

        if self.occupancy and self.has_robot_location and self.nav_sp:
            state_min = (-int(round(self.plan_horizon)), -int(round(self.plan_horizon)))
            state_max = (int(round(self.plan_horizon)), int(round(self.plan_horizon)))
            # Round initial, goal positions to grid resolution
            x_init = round_pt_to_grid(robot_translation[:2], self.plan_resolution)
            x_goal = round_pt_to_grid(self.nav_sp[:2], self.plan_resolution)

            astar = AStar(state_min, state_max, x_init, x_goal, self.occupancy,
                          self.plan_resolution)

            rospy.loginfo("Computing navigation plan")
            if astar.solve():
                # If initial state == goal, path len == 1
                # Handle case where A* solves, but no 2nd element -> don't send msg
                if len(astar.path) < 4:
                    rospy.loginfo("Path goal matches current state")

                # Typical use case
                else:
                    # Next waypoint calculations
                    wp_x = astar.path[3][0]
                    wp_y = astar.path[3][1]

                    # Far from goal - do intermediate heading calcs
                    if len(astar.path) > 4:
                        dx = wp_x - robot_translation[0]
                        dy = wp_y - robot_translation[1]
                        wp_th = np.arctan2(dy,dx)
                    # Next point on path is the goal - use final goal pose
                    else:
                        wp_th = self.nav_sp[2]

                    # Publish next waypoint
                    pose_sp = (wp_x,wp_y,wp_th)
                    msg = Float32MultiArray()
                    msg.data = pose_sp
                    self.pose_sp_pub.publish(msg)

                    # Publish full path
                    path_msg = Path()
                    path_msg.header.frame_id = 'map'
                    for state in astar.path:
                        pose_st = PoseStamped()
                        pose_st.pose.position.x = state[0]
                        pose_st.pose.position.y = state[1]
                        pose_st.header.frame_id = 'map'
                        path_msg.poses.append(pose_st)
                    self.nav_path_pub.publish(path_msg)

            else:
                rospy.logwarn("Could not find path")

    def run(self):
        rospy.spin()


def round_pt_to_grid(pt, grid_res):
    """Rounds coordinate point to nearest grid coordinates"""
    steps = 1 / grid_res
    return tuple([round(coord*steps) / steps for coord in pt])


if __name__ == '__main__':
    nav = Navigator()
    nav.run()